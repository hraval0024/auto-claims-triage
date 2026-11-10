"""Download the approved eval images (eval/candidates_proposed.csv) to data/eval/ (gitignored).

Polite to Wikimedia: identifying UA with the repo URL as contact, a delay between requests,
retry-after honored on 429. Bytes go through the app's SSRF-guarded fetcher.
Writes eval/manifest.json (ids, titles, links, licenses, authors, sha256). Never commits images.

Usage: uv run python -m scripts.fetch_eval
"""

import csv
import hashlib
import json
import time
from pathlib import Path

from app.ssrf import UrlFetchError, fetch_image
from scripts.fetch_samples import DELAY_S, USER_AGENT, commons_metadata

OUT = Path("data/eval")
MANIFEST = Path("eval/manifest.json")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(open("eval/candidates_proposed.csv")))
    entries, failed = [], []
    for r in rows:
        path = OUT / f"{r['image_id']}.jpg"
        e = {"image_id": r["image_id"], "bucket": r["bucket"], "commons_title": r["commons_title"]}
        try:
            meta = commons_metadata(r["commons_title"])
            time.sleep(DELAY_S)
            if meta["license"] != r["license"]:
                print(f"WARNING {r['image_id']}: license now {meta['license']} (was {r['license']})")
            e.update(file_page=meta["file_page"], image_url=meta["image_url"], license=meta["license"],
                     license_url=meta["license_url"], author=meta["author"])
            if not path.exists():
                for attempt in range(3):
                    try:
                        path.write_bytes(fetch_image(meta["image_url"], user_agent=USER_AGENT))
                        break
                    except UrlFetchError as err:
                        if attempt == 2:
                            raise
                        time.sleep(10 * (attempt + 1))  # back off (e.g. HTTP 429)
                time.sleep(DELAY_S)
            e["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            print(f"ok   {r['image_id']} {path.stat().st_size // 1024} KB")
        except Exception as err:  # report every failure; never substitute an image
            e["error"] = str(err)
            failed.append(r["image_id"])
            print(f"FAIL {r['image_id']}: {err}")
        entries.append(e)
    removed = json.loads(MANIFEST.read_text()).get("removed", []) if MANIFEST.exists() else []
    MANIFEST.write_text(json.dumps({
        "_note": "Phase 4 eval images. Files live in data/eval/ (gitignored) and are never committed. "
                 "DEV images (samples/manifest.json) are excluded. Label provenance is recorded per row in eval/labels/.",
        "images": entries, "removed": removed}, indent=2, ensure_ascii=False) + "\n")
    print(f"done: {len(entries) - len(failed)} ok, {len(failed)} failed {failed}")


if __name__ == "__main__":
    main()
