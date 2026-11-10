"""Run one claim from the command line and print the full JSON (including raw model output).

Usage: uv run python -m scripts.run_claim [--model ID] [--effort LEVEL] PATH_OR_URL [PATH_OR_URL ...]
All inputs together form ONE claim (multi-photo).
"""

import argparse
import sys
from pathlib import Path

from app.intake import IntakeError
from app.pipeline import run_claim
from app.ssrf import fetch_image


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--model")
    ap.add_argument("--effort")
    args = ap.parse_args()
    try:
        images = [fetch_image(s) if s.startswith(("http://", "https://")) else Path(s).read_bytes() for s in args.inputs]
        result = run_claim(images, model_id=args.model, effort=args.effort, include_raw=True)
    except IntakeError as e:
        print(f"REJECTED: {e}", file=sys.stderr)
        return 2
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
