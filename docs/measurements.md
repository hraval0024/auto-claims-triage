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

About $0.21 of the $30 ceiling (2026-11-10).
