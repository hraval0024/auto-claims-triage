"""Find candidate eval images on Wikimedia Commons by METADATA ONLY (no image downloads).

Records title, file page, license, author, size and description for each hit, keeps only free
licenses, and drops anything already in samples/manifest.json (DEV images).
Writes eval/candidates_raw.json for human review.

Usage: uv run python -m scripts.find_eval_candidates
"""

import json
import re
import time
from pathlib import Path

import httpx

USER_AGENT = "auto-claims-triage-prototype/0.1 (https://github.com/hraval0024/auto-claims-triage)"
API = "https://commons.wikimedia.org/w/api.php"
FREE = re.compile(r"^(CC0|Public domain|CC BY(-SA)? [0-9.]+)", re.I)

QUERIES = {
    "minor": ["scratched car paint", "car door dent", "dented car", "scuffed bumper", "car bumper scratch",
              "cracked tail light car", "broken taillight", "broken side mirror car", "keyed car scratch",
              "hail damage car", "minor car accident bumper", "fender bender"],
    "moderate_severe": ["car accident damage front", "rear-end collision car damage", "car crash side damage"],
    "no_damage": ["parked car side view", "car rear view parked street"],
}


def get(params: dict) -> dict:
    for _ in range(6):
        r = httpx.get(API, params=params, headers={"User-Agent": USER_AGENT}, timeout=20)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("retry-after", "10")) + 1)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("rate limited")


def strip(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


def main() -> None:
    dev_titles = {s.get("commons_title") for s in json.load(open("samples/manifest.json"))["samples"]}
    seen, out = set(), []
    for bucket, qs in QUERIES.items():
        for q in qs:
            d = get(dict(action="query", format="json", generator="search", gsrnamespace=6, gsrlimit=12,
                         gsrsearch=f"{q} filetype:bitmap", prop="imageinfo", iiprop="size|url|extmetadata",
                         iiextmetadatafilter="LicenseShortName|Artist|ImageDescription"))
            time.sleep(3)
            for p in d.get("query", {}).get("pages", {}).values():
                t = p["title"]
                if t in seen or t in dev_titles:
                    continue
                seen.add(t)
                ii = p["imageinfo"][0]
                m = ii.get("extmetadata", {})
                lic = m.get("LicenseShortName", {}).get("value", "")
                out.append({
                    "bucket_query": bucket, "query": q, "commons_title": t, "file_page": ii["descriptionurl"],
                    "license": lic, "free_license": bool(FREE.match(lic)),
                    "author": strip(m.get("Artist", {}).get("value", "")),
                    "width": ii["width"], "height": ii["height"],
                    "description": strip(m.get("ImageDescription", {}).get("value", ""))[:200],
                })
            print(f"{bucket:16} {q:32} total={len(out)}", flush=True)
    Path("eval").mkdir(exist_ok=True)
    Path("eval/candidates_raw.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
