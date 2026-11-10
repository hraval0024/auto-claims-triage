# Measurements log

Raw measured numbers, dated, with the run they came from. Feeds docs/HANDOFF.md. Small n is
marked as such; none of these are eval results.

## Input tokens by component (count_tokens, 2026-11-10)

claude-sonnet-5-5, extract_v2, schema 1.1.0, image resized to 1568x1045:

| Component | Tokens |
|---|---|
| System prompt (instructions + rubric) | 2,228 |
| Output JSON schema (structured outputs) | 3,091 |
| One photo (image + its label text) | about 2,150 |
| **1-photo request total** | **7,490** |
| 5-photo request total | 16,042 (about 2,138 per extra photo) |

The static prefix (system prompt + schema, 5,321 tokens) is 71% of a 1-photo request. The
schema is the largest single part; trimming field descriptions is a possible lever (not done).

## Prompt caching (2026-11-10, `data/runs/cache_experiment.txt`, DEV image altima_accident, n=3 per arm)

| Arm | Uncached input | Cache write | Cache read | Cost per call | Latency (s) |
|---|---|---|---|---|---|
| No cache | 7,490 | 0 | 0 | $0.0230-0.0243 | 7.5, 9.0, 10.7 |
| Cache, first call (write) | 2,169 | 5,321 | 0 | $0.0266 | 14.2 |
| Cache, hits | 2,169 | 0 | 5,321 | $0.0142-0.0144 | 19.3, 9.5 |

- The cache covers the system prompt AND the schema (5,321 tokens cached).
- Cost: a cache hit is about 39% cheaper than uncached. The first call per 5-minute window costs about 13% more.
- Latency: no measurable improvement at n=3. Output generation (about 800-950 output tokens including thinking) dominates.

## p95 latency risk (target: single image p95 < 15 s; an assumption to validate)

- **Sonnet 5.5, single photo:** 7 calls so far, 7.5-19.3 s; 1 of 7 was over 15 s. Too few calls for a real p95.
- **Opus 5.5, single photo:** 1 call, 14.7 s at effort medium, 1,471 output tokens. Thinking can't be turned off on Opus 5.5, so it sits at the target with no headroom. Likely p95 is over 15 s.
- **Multi-photo:** each extra photo adds about 2,140 input tokens, and output grows with the number of damage observations (one per photo per damage). A 5-photo claim is likely to go well over 15 s on any model. Expect the target to hold for single photos on Sonnet/Haiku only, and plan for the UI to show progress on multi-photo claims.
- Levers not yet tried: effort `low`, trimming schema descriptions, a lower image resolution cap. Each needs an eval check for quality loss.

## Cost per call (measured)

| Model | Effort | Cost per 1-photo call | Basis |
|---|---|---|---|
| claude-sonnet-5-5 | medium | $0.023-0.024 uncached; $0.014 with a cache hit | 8 calls |
| claude-opus-5-5 | medium | $0.065 with a cache write (about $0.040 estimated for a hit) | 1 call |
| claude-haiku-5-5 | - | not measured yet | - |

## Spend to date

About $1.80 of the $30 ceiling (2026-11-10): smoke/caching $0.21, Opus side checks $0.20, latency experiment $1.26, Phase 1 case runs $0.13.

## Latency levers, one at a time (2026-11-10, `data/runs/latency_exp.jsonl`, `scripts/latency_experiment.py`)

claude-sonnet-5-5, extract_v2, caching on. 7 DEV images x 4 repeats = **28 calls per arm**, 112
total, 0 failed, $1.26. Calls interleaved across arms. p95 is nearest-rank over 28 calls (the
27th value), so it is a rough estimate. Quality = agreement with the baseline arm, compared with
the baseline's agreement with itself (noise floor). No labels, so this is consistency, not accuracy.

| Arm | n | p50 s | p95 s | max s | Output tokens | $/call | Cue words | Gate agrees | Item overlap | Panel overlap | Max severity agrees | F1 side correct |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline (medium, 1568px) | 28 | 5.5 | 9.5 | 9.5 | 706 | 0.0120 | 16.6 | 100% | 0.75 (floor) | 0.86 (floor) | 100% | 0/4 |
| effort low | 28 | 5.1 | 8.8 | 9.1 | 683 | 0.0113 | 15.5 | 100% | 0.71 | 0.84 | 100% | 0/4 |
| cues at most 8 words | 28 | 5.2 | 8.8 | 11.5 | 738 | 0.0125 | 6.1 | 100% | 0.68 | 0.80 | 86% | 0/4 |
| 1024px cap | 28 | 5.1 | 6.5 | 6.7 | 671 | 0.0092 | 14.5 | 86% | 0.52 | 0.71 | 86% | 0/4 |

Findings:
- **Effort low:** small gain (p95 -0.7 s, -6% cost); quality stays near the noise floor. Not adopted yet: the gain is within run-to-run variation. Recheck in the Phase 4 eval against labels.
- **Short cues:** cue text fell from 17 to 6 words but total output tokens did not fall (thinking tokens dominate), and severity agreement dropped. Rejected.
- **1024px cap:** fastest (p95 6.5 s) and 23% cheaper, but gate, item and severity agreement all dropped clearly below the noise floor. Rejected: resolution matters for damage detail.
- **Latency varies over time:** this run had p95 9.5 s and nothing over 15 s, while 1 of 7 earlier single-photo Sonnet calls took 19.3 s. A per-request p95 for the demo needs an n of 50+ on the deployed service (Phase 5).
- F1 side remains wrong on Sonnet in every arm (16/16).
