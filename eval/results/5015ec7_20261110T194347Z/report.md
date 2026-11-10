# Eval results 5015ec7_20261110T194347Z (scored with eval_v2 at da68f67)
Run commit 5015ec79edd856a529844bb79485b60afb2b78ff | 34 images (Wikimedia Commons; DEV excluded) | prompt extract_v2 schema 1.3.0 rules routing_v1.1 cost cost_table_v1 | effort medium
SMALL SET: n=34. Labels: ['ChatGPT GPT-6.1 Sol-Light (labeled 2026-11-10); model-generated, not human-verified'] -> AGREEMENT with one other model, NOT accuracy against adjusters.
Common subset: 21 images assessed by the labels and all three models: eval_002, eval_005, eval_008, eval_009, eval_010, eval_011, eval_014, eval_015, eval_018, eval_019, eval_021, eval_022, eval_023, eval_024, eval_025, eval_029, eval_030, eval_031, eval_032, eval_033, eval_034.
Cost accuracy: N/A: no public ground truth.

| Metric | Opus 5.5 all | Opus 5.5 common | Sonnet 5.5 all | Sonnet 5.5 common | Haiku 5.5 all | Haiku 5.5 common |
|---|---|---|---|---|---|---|
| Make accuracy | 100.0% (20/20) | 100.0% (16/16) | 87.5% (14/16) | 87.5% (14/16) | 85.7% (18/21) | 81.2% (13/16) |
| Model accuracy | 82.4% (14/17) | 78.6% (11/14) | 64.3% (9/14) | 64.3% (9/14) | 44.4% (8/18) | 50.0% (7/14) |
| Color accuracy | 96.3% (26/27) | 100.0% (21/21) | 100.0% (21/21) | 100.0% (21/21) | 96.4% (27/28) | 100.0% (21/21) |
| Year range overlaps label | 100.0% (4/4) | 100.0% (3/3) | 100.0% (3/3) | 100.0% (3/3) | 100.0% (4/4) | 100.0% (3/3) |
| Panel precision / recall | 90.2% / 73.3% | 91.1% / 72.9% | 81.0% / 67.1% | 81.0% / 67.1% | 90.5% / 50.0% | 94.6% / 50.0% |
| Damage-type precision / recall | 81.4% / 55.6% | 81.6% / 54.4% | 79.5% / 54.4% | 79.5% / 54.4% | 78.9% / 46.9% | 81.2% / 45.6% |
| Side agreement (matched L/R panels) | 91.2% (n=34) | 96.8% (n=31) | 70.0% (n=30) | 70.0% (n=30) | 95.7% (n=23) | 95.5% (n=22) |
| Severity exact / within 1 / weighted kappa | 81.8% / 100.0% / 0.826 | 80.4% / 100.0% / 0.8 | 68.1% / 97.9% / 0.679 | 68.1% / 97.9% / 0.679 | 60.5% / 100.0% / 0.588 | 60.0% / 100.0% / 0.603 |
| Sev-3 panels found / at sev 3+ | 76.6% / 72.3% (n=47) | 75.0% / 70.5% (n=44) | 70.5% / 63.6% (n=44) | 70.5% / 63.6% (n=44) | 54.2% / 45.8% (n=48) | 52.3% / 43.2% (n=44) |
| Sev-4 panels found / rated 4 | 100.0% / 87.5% (n=8) | 100.0% / 87.5% (n=8) | 100.0% / 87.5% (n=8) | 100.0% / 87.5% (n=8) | 75.0% / 0.0% (n=8) | 75.0% / 0.0% (n=8) |
| Gate agreement (all 34) | 30/34 | - | 25/34 | - | 32/34 | - |
| Images assessed by labels AND model | 27 | - | 21 | - | 28 | - |
| Cost range high/low (median) | 4.11x | - | 4.25x | - | 5.39x | - |
| Free-guess point outside engine range | 20.0% (3/15) | - | 30.0% (3/10) | - | 20.0% (4/20) | - |
| request_more_photos share (all 34) | 41.2% | - | 52.9% | - | 44.1% | - |
| Latency p50 / max, s (uncached, n) | 13.79 / 20.48 (n=34) | - | 4.84 / 11.23 (n=34) | - | 9.175 / 16.89 (n=34) | - |
| Cost per claim (extraction mean) | $0.03376 | - | $0.01136 | - | $0.00114 | - |
| Repeatability: same routing / same max severity | 70.0% / 90.0% | - | 90.0% / 100.0% | - | 100.0% / 90.0% | - |

## Sensitivity: excluding audited labels eval_016, eval_017, eval_023, eval_029, eval_030, eval_033

| Metric | Opus 5.5 | Sonnet 5.5 | Haiku 5.5 |
|---|---|---|---|
| Make accuracy | 100.0% (16/16) | 91.7% (11/12) | 87.5% (14/16) |
| Model accuracy | 92.3% (12/13) | 70.0% (7/10) | 46.2% (6/13) |
| Color accuracy | 95.7% (22/23) | 100.0% (17/17) | 95.7% (22/23) |
| Year range overlaps label | 100.0% (3/3) | 100.0% (2/2) | 100.0% (3/3) |

## F5 before / after (eval_v1 as run -> eval_v2, same saved runs, no new model calls)

| Metric | Opus 5.5 | Sonnet 5.5 | Haiku 5.5 |
|---|---|---|---|
| Make accuracy | 95.0% (19/20) -> 100.0% (20/20) | 81.2% (13/16) -> 87.5% (14/16) | 81.0% (17/21) -> 85.7% (18/21) |
| Model accuracy | 82.4% (14/17) -> 82.4% (14/17) | 64.3% (9/14) -> 64.3% (9/14) | 44.4% (8/18) -> 44.4% (8/18) |
| Color accuracy | 96.3% (26/27) -> 96.3% (26/27) | 100.0% (21/21) -> 100.0% (21/21) | 96.4% (27/28) -> 96.4% (27/28) |
