"""Run the Phase 1 cases and save each full JSON result to runs/phase1/<case>.json.

Usage: uv run python -m scripts.run_phase1_cases [CASE_ID ...]   (default: all available)
"""

import sys
from pathlib import Path

from app.pipeline import run_claim

S = Path("data/samples")
CASES = {
    "case1_clean": ["case1_clean_cirrus.jpg"],
    "case2_hard": ["case2_hard_pohang.jpg"],
    "case3_multidamage": ["case3_multidamage_starex.jpg"],
    "case4_night": ["case4_night_crash.jpg"],
    "case5a_noncar_obvious": ["case5a_noncar_obvious.jpg"],
    "case5b_noncar_borderline": ["case5b_noncar_borderline.jpg"],
    "case6_injection": ["case6_injection_cirrus.jpg"],
    "case7_screenshot": ["case7_screenshot.png"],
    "case7b_screenshot_cropped": ["case7b_screenshot.png"],
    "case8_multiphoto": ["case8_multiphoto_mercedes_a.jpg", "case8_multiphoto_mercedes_b.jpg"],
}
OUT = Path("runs/phase1")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    wanted = sys.argv[1:] or list(CASES)
    for case in wanted:
        paths = [S / f for f in CASES[case]]
        if not all(p.exists() for p in paths):
            print(f"SKIP {case}: missing {[str(p) for p in paths if not p.exists()]}")
            continue
        r = run_claim([p.read_bytes() for p in paths], include_raw=True)
        (OUT / f"{case}.json").write_text(r.model_dump_json(indent=2) + "\n")
        print(f"{case:26} status={r.status:11} {r.latency_ms / 1000:5.1f}s ${r.usage.cost_usd if r.usage else 0:.4f}")


if __name__ == "__main__":
    main()
