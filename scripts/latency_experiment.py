"""Latency-lever experiment on DEV images: baseline vs one change at a time.

Arms (Sonnet 5.5, extract_v2, prompt caching on):
  baseline     effort=medium, 1568px, normal cues
  effort_low   effort=low
  short_cues   cues field limited to 8 words (schema description only)
  res_1024     image long side capped at 1024px

Calls are interleaved (repeat -> image -> arm) so drift over time hits every arm equally.
Writes one JSON line per call to data/runs/latency_exp.jsonl.

Usage: uv run python -m scripts.latency_experiment [REPEATS]
"""

import copy
import json
import sys
import time
from pathlib import Path

from app import llm
from app.config import settings
from app.intake import prepare_image

IMAGES = ["altima_accident", "case1_clean_cirrus", "case2_hard_pohang", "case3_multidamage_starex",
          "case4_night_crash", "case8_multiphoto_mercedes_a", "case8_multiphoto_mercedes_b"]
MODEL = "claude-sonnet-5-5"
OUT = Path("data/runs/latency_exp.jsonl")

BASE_SCHEMA = llm.OUTPUT_SCHEMA
SHORT_SCHEMA = copy.deepcopy(BASE_SCHEMA)
SHORT_SCHEMA["$defs"]["DamageObservation"]["properties"]["cues"]["description"] = (
    "At most 8 words naming the key visible cues, e.g. 'sharp crease, paint cracked'."
)

ARMS = {
    "baseline": dict(effort="medium", res=1568, schema=BASE_SCHEMA),
    "effort_low": dict(effort="low", res=1568, schema=BASE_SCHEMA),
    "short_cues": dict(effort="medium", res=1568, schema=SHORT_SCHEMA),
    "res_1024": dict(effort="medium", res=1024, schema=BASE_SCHEMA),
}


def prepared(name: str, res: int) -> bytes:
    settings.model_image_long_side_px = res
    try:
        return prepare_image(Path(f"data/samples/{name}.jpg").read_bytes()).jpeg_bytes
    finally:
        settings.model_image_long_side_px = 1568


def main() -> None:
    repeats = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    imgs = {(n, r): prepared(n, r) for n in IMAGES for r in {a["res"] for a in ARMS.values()}}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a") as f:
        for rep in range(repeats):
            for name in IMAGES:
                for arm, cfg in ARMS.items():
                    llm.OUTPUT_SCHEMA = cfg["schema"]
                    t = time.monotonic()
                    try:
                        out, u = llm.call_model([imgs[(name, cfg["res"])]], model_id=MODEL, effort=cfg["effort"])
                        rec = dict(
                            ok=True, view=out.photos[0].camera_view.value,
                            issues=[i.code.value for i in out.photos[0].issues],
                            items=[[d.panel.value, d.side.value, d.damage_type.value, d.severity] for d in out.damage],
                            in_tok=u.input_tokens, read=u.cache_read_tokens, write=u.cache_write_tokens,
                            out_tok=u.output_tokens, cost=u.cost_usd, attempts=u.attempts,
                            cue_words=[len(d.cues.split()) for d in out.damage],
                        )
                    except llm.LLMError as e:
                        rec = dict(ok=False, error=str(e), cost=e.usage.cost_usd)
                    rec.update(arm=arm, image=name, rep=rep, latency_s=round(time.monotonic() - t, 2))
                    f.write(json.dumps(rec) + "\n")
                    f.flush()
                    print(f"rep{rep} {name:28} {arm:11} {rec['latency_s']:5.1f}s ok={rec['ok']}", flush=True)
    llm.OUTPUT_SCHEMA = BASE_SCHEMA


if __name__ == "__main__":
    main()
