"""Import externally produced labels (e.g. ChatGPT) into eval/labels/, validating every value.

Strict: bad rows are REPORTED, never fixed. The only change made is trimming leading/trailing
whitespace, and the report says so. If any row for an image is invalid, the whole image (its
image row and all its damage rows) is rejected, so partial labels can't bias recall.

Usage:
  uv run python -m scripts.import_labels --label-source "ChatGPT (GPT-x, 2026-11-10)" \
      --images batch1_images.csv batch2_images.csv --damage batch1_damage.csv batch2_damage.csv
  Add --dry-run to validate without writing; --replace to overwrite existing labels.
"""

import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from scripts.label_schema import (
    CAMERA_VIEWS, DAMAGE_TYPES, DMG_COLS, GATE_BLOCKING, GATE_NONBLOCKING, IMG_COLS, LABEL_IMG_COLS,
    PANELS, SEVERITIES, SIDES, YEAR_MAX, YEAR_MIN, YES_NO,
)

MANIFEST = Path("eval/manifest.json")


def read(path: Path, expected: list[str], errors: list[str]) -> list[tuple[int, dict]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = [h.strip() for h in next(reader, [])]
        if header != expected:
            errors.append(f"{path}: header must be exactly {','.join(expected)} (got {','.join(header)}); file rejected")
            return []
        rows = []
        for n, raw in enumerate(reader, start=2):
            if not any(c.strip() for c in raw):
                continue
            if len(raw) != len(expected):
                errors.append(f"{path}:{n}: expected {len(expected)} columns, got {len(raw)}")
                rows.append((n, None))
                continue
            rows.append((n, {k: v.strip() for k, v in zip(expected, raw)}))
        return rows


def check_image(r: dict) -> list[str]:
    e = []
    if r["should_pass_gate"] not in YES_NO:
        e.append(f"should_pass_gate '{r['should_pass_gate']}' not in {YES_NO}")
    elif r["should_pass_gate"] == "no" and r["gate_reason"] not in GATE_BLOCKING:
        e.append(f"should_pass_gate=no needs gate_reason in {GATE_BLOCKING} (got '{r['gate_reason']}')")
    elif r["should_pass_gate"] == "yes" and r["gate_reason"] not in [""] + GATE_NONBLOCKING:
        e.append(f"should_pass_gate=yes allows gate_reason empty or {GATE_NONBLOCKING} (got '{r['gate_reason']}')")
    for k in ("make", "model", "color"):
        if not r[k]:
            e.append(f"{k} is empty (use 'unknown')")
    ys, ye = r["year_start"], r["year_end"]
    if bool(ys) != bool(ye):
        e.append("year_start and year_end must both be filled or both empty")
    elif ys:
        if not (ys.isdigit() and ye.isdigit()):
            e.append(f"years must be whole numbers (got '{ys}', '{ye}')")
        elif not (YEAR_MIN <= int(ys) <= int(ye) <= YEAR_MAX):
            e.append(f"years must satisfy {YEAR_MIN} <= start <= end <= {YEAR_MAX} (got {ys}-{ye})")
    if r["camera_view"] not in CAMERA_VIEWS:
        e.append(f"camera_view '{r['camera_view']}' not allowed")
    if r["has_visible_damage"] not in YES_NO:
        e.append(f"has_visible_damage '{r['has_visible_damage']}' not in {YES_NO}")
    return e


def check_damage(r: dict) -> list[str]:
    e = []
    for k, allowed in (("panel", PANELS), ("side", SIDES), ("damage_type", DAMAGE_TYPES), ("severity", SEVERITIES)):
        if r[k] not in allowed:
            e.append(f"{k} '{r[k]}' not allowed")
    return e


def has_labels(path: Path) -> bool:
    if not path.exists():
        return False
    with path.open(newline="") as f:
        return any(any(v for k, v in row.items() if k in LABEL_IMG_COLS[1:] + ["panel"]) for row in csv.DictReader(f))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", nargs="+", required=True, type=Path)
    ap.add_argument("--damage", nargs="+", required=True, type=Path)
    ap.add_argument("--label-source", required=True, help='e.g. "ChatGPT (model name, date); model-generated, not human-verified"')
    ap.add_argument("--out-dir", type=Path, default=Path("eval/labels"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--replace", action="store_true")
    a = ap.parse_args(argv)
    if not a.label_source.strip():
        ap.error("--label-source must not be empty")

    manifest = {e["image_id"]: e for e in json.loads(MANIFEST.read_text())["images"] if "sha256" in e}
    removed = {e["image_id"] for e in json.loads(MANIFEST.read_text()).get("removed", [])}
    file_errors: list[str] = []
    bad: dict[str, list[str]] = defaultdict(list)  # image_id -> reasons (whole image rejected)
    orphan: list[str] = []
    images: dict[str, dict] = {}
    where: dict[str, str] = {}

    for path in a.images:
        for n, r in read(path, LABEL_IMG_COLS, file_errors):
            if r is None:
                continue
            iid, loc = r["image_id"], f"{path}:{n}"
            if iid in removed:
                file_errors.append(f"{loc}: {iid} was removed from the eval set; row ignored")
                continue
            if iid not in manifest:
                file_errors.append(f"{loc}: unknown image_id '{iid}'; row ignored")
                continue
            if iid in images:
                bad[iid].append(f"{loc}: duplicate image row (first at {where[iid]})")
                continue
            images[iid], where[iid] = r, loc
            bad[iid] += [f"{loc}: {m}" for m in check_image(r)]

    damage: dict[str, list[dict]] = defaultdict(list)
    seen = defaultdict(set)
    for path in a.damage:
        for n, r in read(path, DMG_COLS, file_errors):
            if r is None:
                continue
            iid, loc = r["image_id"], f"{path}:{n}"
            if iid not in images:
                orphan.append(f"{loc}: damage row for '{iid}', which has no image row; ignored")
                continue
            errs = check_damage(r)
            key = (r["panel"], r["side"], r["damage_type"])
            if key in seen[iid]:
                errs.append(f"duplicate damage item {key}")
            seen[iid].add(key)
            bad[iid] += [f"{loc}: {m}" for m in errs]
            damage[iid].append(r)

    for iid, r in images.items():
        n_dmg = len(damage[iid])
        if r["has_visible_damage"] == "no" and n_dmg:
            bad[iid].append(f"{where[iid]}: has_visible_damage=no but {n_dmg} damage row(s)")
        if r["has_visible_damage"] == "yes" and r["should_pass_gate"] == "yes" and not n_dmg:
            bad[iid].append(f"{where[iid]}: has_visible_damage=yes and should_pass_gate=yes but no damage rows")

    rejected = sorted(i for i in images if bad[i])
    accepted = sorted(i for i in images if not bad[i])
    missing = sorted(set(manifest) - set(images))

    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report = [f"Label import report {ts}", f"label_source: {a.label_source}",
              "Inputs (sha256): " + ", ".join(f"{p} {hashlib.sha256(p.read_bytes()).hexdigest()[:12]}" for p in a.images + a.damage),
              "Only change made to values: leading/trailing whitespace trimmed. Nothing else is altered or fixed.",
              f"Accepted images: {len(accepted)} (damage rows: {sum(len(damage[i]) for i in accepted)})",
              f"Rejected images: {len(rejected)}", f"Manifest images with no label row: {len(missing)} {missing if missing else ''}"]
    for i in rejected:
        report += [f"  REJECTED {i}:"] + [f"    - {m}" for m in bad[i]]
    if file_errors or orphan:
        report += ["File / row problems:"] + [f"  - {m}" for m in file_errors + orphan]
    print("\n".join(report))

    out_img, out_dmg = a.out_dir / "images_labels.csv", a.out_dir / "damage_labels.csv"
    if a.dry_run:
        print("\nDry run: nothing written.")
        return 1 if (rejected or file_errors or orphan) else 0
    if not a.replace and (has_labels(out_img) or has_labels(out_dmg)):
        print(f"\nRefusing to overwrite existing labels in {a.out_dir} (use --replace).")
        return 2
    a.out_dir.mkdir(parents=True, exist_ok=True)
    with out_img.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=IMG_COLS)
        w.writeheader()
        for i in accepted:
            m = manifest[i]
            w.writerow(images[i] | {"commons_title": m["commons_title"], "license": m["license"], "author": m["author"],
                                    "label_source": a.label_source})
    with out_dmg.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=DMG_COLS)
        w.writeheader()
        for i in accepted:
            w.writerows(damage[i])
    (a.out_dir / "import_report.txt").write_text("\n".join(report) + "\n")
    print(f"\nWrote {out_img}, {out_dmg} and {a.out_dir / 'import_report.txt'}.")
    return 1 if (rejected or file_errors or orphan) else 0


if __name__ == "__main__":
    sys.exit(main())
