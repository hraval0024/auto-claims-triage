"""Check the eval set against DEV images: exact sha256 and perceptual (dHash) near-duplicates.
Also checks near-duplicates within the eval set and that every file passes app intake.
Writes eval/dev_overlap_check.txt.

Usage: uv run python -m scripts.check_eval_overlap
"""

import hashlib
import json
from pathlib import Path

from PIL import Image

from app.intake import prepare_image

NEAR = 10  # dHash Hamming distance (of 64 bits) treated as "same photo"


def dhash(path: Path, size: int = 8) -> int:
    im = Image.open(path).convert("L").resize((size + 1, size), Image.LANCZOS)
    px = list(im.get_flattened_data()) if hasattr(im, "get_flattened_data") else list(im.getdata())
    bits = (px[r * (size + 1) + c] > px[r * (size + 1) + c + 1] for r in range(size) for c in range(size))
    return sum(1 << i for i, b in enumerate(bits) if b)


def ham(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def main() -> None:
    ev = json.load(open("eval/manifest.json"))["images"]
    dev_files = [p for p in Path("data/samples").iterdir() if p.suffix.lower() in (".jpg", ".png")]
    dev_sha = {d["sha256"] for d in json.load(open("samples/manifest.json"))["samples"] if "sha256" in d}
    dev_sha |= {hashlib.sha256(p.read_bytes()).hexdigest() for p in dev_files}
    dev_dh = {p.name: dhash(p) for p in dev_files}

    exact = [e["image_id"] for e in ev if e["sha256"] in dev_sha]
    ev_dh, near_dev = {}, []
    for e in ev:
        p = Path(f"data/eval/{e['image_id']}.jpg")
        prepare_image(p.read_bytes())  # raises if app intake would reject the file
        ev_dh[e["image_id"]] = h = dhash(p)
        d, name = min((ham(h, x), n) for n, x in dev_dh.items())
        if d <= NEAR:
            near_dev.append((e["image_id"], name, d))
    ids = list(ev_dh)
    within = [(a, b, ham(ev_dh[a], ev_dh[b])) for i, a in enumerate(ids) for b in ids[i + 1:] if ham(ev_dh[a], ev_dh[b]) <= NEAR]

    lines = [
        f"Eval images checked: {len(ev)}; DEV hashes: {len(dev_sha)}; DEV files for perceptual check: {len(dev_files)}",
        f"Exact sha256 matches with DEV: {exact or 'none'}",
        f"Perceptual near-duplicates of DEV (dHash distance <= {NEAR} of 64): {near_dev or 'none'}",
        f"Near-duplicates within the eval set: {within or 'none'}",
        f"Duplicate sha256 within eval set: {len(ev) - len({e['sha256'] for e in ev})}",
        "All files pass app intake (magic bytes, size, dimensions): yes",
    ]
    Path("eval/dev_overlap_check.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
