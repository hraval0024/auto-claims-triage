"""Repeatability: run case 1 (clean) and case 6 (same photo + injection text) N times each,
interleaved, Sonnet 5.5, no baseline call. Writes data/runs/repeat_check.jsonl.

Usage: uv run python -m scripts.repeat_check [N]
"""

import json
import sys
from pathlib import Path

from app.pipeline import run_claim

CASES = {"clean": "data/samples/case1_clean_cirrus.jpg", "injection": "data/samples/case6_injection_cirrus.jpg"}
OUT = Path("data/runs/repeat_check.jsonl")


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    with OUT.open("w") as f:
        for rep in range(n):
            for name, path in CASES.items():
                r = run_claim([Path(path).read_bytes()], include_llm_baseline=False)
                rec = {
                    "case": name, "rep": rep, "status": r.status, "routing": r.routing.outcome, "flags": r.flags,
                    "make": r.vehicle.make.value if r.vehicle else None, "model": r.vehicle.model.value if r.vehicle else None,
                    "items": [[d.panel.value, d.side.value, d.damage_type.value, d.severity, d.confidence.value] for d in r.damage],
                    "cost_status": r.cost.status if r.cost else None,
                    "low": r.cost.low_usd if r.cost else None, "high": r.cost.high_usd if r.cost else None,
                    "latency_s": r.latency_ms / 1000, "usd": r.usage.cost_usd if r.usage else 0,
                }
                f.write(json.dumps(rec) + "\n")
                f.flush()
                print(f"rep{rep} {name:9} {r.routing.outcome:20} ${rec['low']}-{rec['high']} items={len(rec['items'])}", flush=True)


if __name__ == "__main__":
    main()
