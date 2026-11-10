# Eval results 5015ec7_20261110T194347Z
Commit 5015ec79edd856a529844bb79485b60afb2b78ff | 34 images (Wikimedia Commons, see eval/manifest.json; DEV images excluded) | prompt extract_v2 schema 1.3.0 rules routing_v1.1 cost cost_table_v1 | effort medium
SMALL SET: n=34. Labels: ['ChatGPT (model not recorded, labeled 2026-11-10); model-generated, not human-verified'] -> AGREEMENT with one other model, NOT accuracy against adjusters.
Cost accuracy: N/A: no public ground truth.

| Metric | opus 5.5 | sonnet 5.5 | haiku 5.5 |
|---|---|---|---|
| Gate agreement (should-pass vs did-pass) | 30/34 | 25/34 | 32/34 |
| Make accuracy | 95.0% (19/20) | 81.2% (13/16) | 81.0% (17/21) |
| Model accuracy | 82.4% (14/17) | 64.3% (9/14) | 44.4% (8/18) |
| Color accuracy | 96.3% (26/27) | 100.0% (21/21) | 96.4% (27/28) |
| Panel precision / recall | 90.2% / 73.3% | 81.0% / 67.1% | 90.5% / 50.0% |
| Damage-type precision / recall | 81.4% / 55.6% | 79.5% / 54.4% | 78.9% / 46.9% |
| Side agreement (matched L/R panels) | 91.2% (n=34) | 70.0% (n=30) | 95.7% (n=23) |
| Severity exact / within 1 / weighted kappa | 81.8% / 100.0% / 0.826 | 68.1% / 97.9% / 0.679 | 60.5% / 100.0% / 0.588 |
| Sev-3 panels found / at sev 3+ | 76.6% / 72.3% (n=47) | 70.5% / 63.6% (n=44) | 54.2% / 45.8% (n=48) |
| Sev-4 panels found / at sev 4 | 100.0% / 87.5% (n=8) | 100.0% / 87.5% (n=8) | 75.0% / 0.0% (n=8) |
| Cost range high/low (median) | 4.11x | 4.25x | 5.39x |
| Baseline guess outside engine range | 20.0% (3/15) | 30.0% (3/10) | 20.0% (4/20) |
| Routing: request_more_photos share | 41.2% | 52.9% | 44.1% |
| Latency p50 / max (s, uncached, n) | 13.79 / 20.48 (n=34) | 4.84 / 11.23 (n=34) | 9.175 / 16.89 (n=34) |
| Cost per claim (extraction mean) | $0.03376 | $0.01136 | $0.00114 |
| Repeatability: routing / max sev same | 70.0% / 90.0% | 90.0% / 100.0% | 100.0% / 90.0% |
