"""Local labeling page for the eval set (used to adjudicate disagreements between labels).

Shows ONLY the image and label controls. Never shows titles (they reveal make/model), sources or
any model output. Saves to the two CSVs. Binds to 127.0.0.1 only.

Usage:
  uv run python -m labeler.server                      # eval/labels/images_labels.csv + damage_labels.csv
  uv run python -m labeler.server --images-csv eval/labels/adjudicated_images.csv \
                                  --damage-csv eval/labels/adjudicated_damage.csv
Then open http://127.0.0.1:8100
"""

import argparse
import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas import CameraView, DamageType, Panel, Side
from scripts.label_schema import DMG_COLS, GATE_BLOCKING, GATE_NONBLOCKING, IMG_COLS

ROOT = Path(__file__).resolve().parent.parent
IMAGE_DIR = ROOT / "data" / "eval"
MANIFEST = ROOT / "eval" / "manifest.json"
LABEL_FIELDS = IMG_COLS[4:]  # the only image columns the page reads or writes (schema: scripts/label_schema.py)

app = FastAPI(title="Eval labeler")
CFG = {"images_csv": ROOT / "eval/labels/images_labels.csv", "damage_csv": ROOT / "eval/labels/damage_labels.csv"}


def ids() -> list[str]:
    return [e["image_id"] for e in json.loads(MANIFEST.read_text())["images"] if "sha256" in e]


def check_id(image_id: str) -> str:
    if image_id not in ids():  # whitelist: no path traversal, only manifest images
        raise HTTPException(404, "unknown image id")
    return image_id


def read_csv(path: Path, cols: list[str]) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return [{c: r.get(c, "") for c in cols} for r in csv.DictReader(f)]


def write_csv(path: Path, cols: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)  # atomic: a crash never leaves a half-written CSV


class DamageLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    panel: Panel
    side: Side
    damage_type: DamageType
    severity: Literal[1, 2, 3, 4]
    label_notes: str = ""


class ImageLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label_source: str = Field(min_length=1)
    should_pass_gate: Literal["", "yes", "no"] = ""
    gate_reason: str = ""
    make: str = ""
    model: str = ""
    color: str = ""
    year_start: int | None = None
    year_end: int | None = None
    camera_view: str = ""
    has_visible_damage: Literal["", "yes", "no"] = ""
    label_notes: str = ""
    damage: list[DamageLabel] = []

    @field_validator("gate_reason")
    @classmethod
    def _gate(cls, v):
        if v not in [""] + GATE_BLOCKING + GATE_NONBLOCKING:
            raise ValueError("invalid gate_reason")
        return v

    @field_validator("camera_view")
    @classmethod
    def _view(cls, v):
        if v not in [""] + [c.value for c in CameraView]:
            raise ValueError("invalid camera_view")
        return v


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "index.html")


@app.get("/api/vocab")
def vocab():
    return {"gate_reason": GATE_BLOCKING + GATE_NONBLOCKING, "camera_view": [c.value for c in CameraView], "panel": [p.value for p in Panel],
            "side": [s.value for s in Side], "damage_type": [d.value for d in DamageType], "severity": [1, 2, 3, 4]}


@app.get("/api/ids")
def list_ids():
    imgs = {r["image_id"]: r for r in read_csv(CFG["images_csv"], IMG_COLS)}
    labeled = {i for i, r in imgs.items() if any(r[c] for c in LABEL_FIELDS if c != "label_source")}
    return {"ids": [{"image_id": i, "labeled": i in labeled} for i in ids()],
            "files": {k: _show(CFG[k]) for k in ("images_csv", "damage_csv")}}


def _show(p: Path) -> str:
    return str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)


@app.get("/api/image/{image_id}")
def image(image_id: str):
    return FileResponse(IMAGE_DIR / f"{check_id(image_id)}.jpg", media_type="image/jpeg")


@app.get("/api/labels/{image_id}")
def get_labels(image_id: str):
    check_id(image_id)
    row = next((r for r in read_csv(CFG["images_csv"], IMG_COLS) if r["image_id"] == image_id), None)
    labels = {c: (row or {}).get(c, "") for c in LABEL_FIELDS}  # never titles/sources
    labels["label_source"] = labels["label_source"] or "candidate (not an adjuster)"
    labels["damage"] = [{c: r[c] for c in DMG_COLS[1:]} for r in read_csv(CFG["damage_csv"], DMG_COLS) if r["image_id"] == image_id]
    return labels


@app.post("/api/labels/{image_id}")
def save_labels(image_id: str, body: ImageLabel):
    check_id(image_id)
    if body.year_start and body.year_end and body.year_start > body.year_end:
        raise HTTPException(422, "year_start is after year_end")
    rows = read_csv(CFG["images_csv"], IMG_COLS)
    manifest = {e["image_id"]: e for e in json.loads(MANIFEST.read_text())["images"]}
    row = next((r for r in rows if r["image_id"] == image_id), None)
    if row is None:  # a fresh labeler file: start the row from the manifest
        m = manifest[image_id]
        row = {c: "" for c in IMG_COLS} | {"image_id": image_id, "commons_title": m["commons_title"],
                                           "license": m["license"], "author": m["author"]}
        rows.append(row)
    for c in LABEL_FIELDS:
        v = getattr(body, c)
        row[c] = "" if v is None else str(v)
    rows.sort(key=lambda r: r["image_id"])
    write_csv(CFG["images_csv"], IMG_COLS, rows)

    dmg = [r for r in read_csv(CFG["damage_csv"], DMG_COLS) if r["image_id"] != image_id]
    dmg += [{"image_id": image_id, "panel": d.panel.value, "side": d.side.value, "damage_type": d.damage_type.value,
             "severity": str(d.severity), "label_notes": d.label_notes} for d in body.damage]
    dmg.sort(key=lambda r: r["image_id"])
    write_csv(CFG["damage_csv"], DMG_COLS, dmg)
    return {"saved": image_id, "damage_rows": len(body.damage)}


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--images-csv", default=str(CFG["images_csv"]))
    ap.add_argument("--damage-csv", default=str(CFG["damage_csv"]))
    ap.add_argument("--port", type=int, default=8100)
    a = ap.parse_args()
    CFG["images_csv"], CFG["damage_csv"] = Path(a.images_csv).resolve(), Path(a.damage_csv).resolve()
    uvicorn.run(app, host="127.0.0.1", port=a.port)


if __name__ == "__main__":
    main()
