# Eval results: Phase 4

**Read this first.** Labels come from a single independent model, **ChatGPT GPT-6.1 Sol-Light**
(labeled 2026-11-10), and are **not human-verified**. The labeler was **not blind**: a contact sheet
showing each image's id and bucket name ("minor", "undamaged", ...) was uploaded with ChatGPT's first
batch. Every number below is **agreement with that model's labels, not accuracy against adjusters.**
Where both models make the same mistake, it scores as correct. The set is small (n = 34).

- **Run:** commit `5015ec7` (prompt extract_v2, schema 1.3.0, rules routing_v1.1, cost_table_v1, effort medium), results in `eval/results/5015ec7_20261110T194347Z/`
- **Scoring:** harness `eval_v2` (commit `da68f67`), re-scoring the SAVED runs: no new model calls. The as-run scoring (eval_v1) is kept as `summary_v1_asrun.json` / `report_v1_asrun.md`.
- **Data:** 34 Wikimedia Commons photos (`eval/manifest.json`; buckets 18 minor, 9 moderate/severe, 7 undamaged); no overlap with DEV images
- **How:** the app's own pipeline (`app.pipeline.run_claim`), image-hash cache OFF, local (the deployed caps and ledger untouched); LLM free-guess baseline called separately; repeatability on 10 fixed images × 3 runs
- **Spend:** $2.98 (Opus $2.17, Sonnet $0.73, Haiku $0.07), 162 claim runs, 0 exceptions
- **Cost accuracy:** N/A: no public ground truth

## Summary

"All" = images that the labels AND that model let through the photo check (Opus 27, Sonnet 21, Haiku 28).
"Common" = the **21 images** assessed by the labels AND all three models (eval_002, 005, 008, 009, 010,
011, 014, 015, 018, 019, 021, 022, 023, 024, 025, 029, 030, 031, 032, 033, 034). The common set equals
Sonnet's own set (Sonnet refused every image either other model refused), so Sonnet's two columns are
identical by construction.

| Metric | Opus all | Opus common | Sonnet all | Sonnet common | Haiku all | Haiku common |
|---|---|---|---|---|---|---|
| Make accuracy | 100% (20/20) | 100% (16/16) | 87.5% (14/16) | 87.5% (14/16) | 85.7% (18/21) | 81.2% (13/16) |
| Model accuracy | 82.4% (14/17) | 78.6% (11/14) | 64.3% (9/14) | 64.3% (9/14) | 44.4% (8/18) | 50.0% (7/14) |
| Color accuracy | 96.3% (26/27) | 100% (21/21) | 100% (21/21) | 100% (21/21) | 96.4% (27/28) | 100% (21/21) |
| Year range overlaps label | 100% (4/4) | 100% (3/3) | 100% (3/3) | 100% (3/3) | 100% (4/4) | 100% (3/3) |
| Panel precision / recall | 90.2% / 73.3% | 91.1% / 72.9% | 81.0% / 67.1% | 81.0% / 67.1% | 90.5% / 50.0% | 94.6% / 50.0% |
| Damage-type precision / recall | 81.4% / 55.6% | 81.6% / 54.4% | 79.5% / 54.4% | 79.5% / 54.4% | 78.9% / 46.9% | 81.2% / 45.6% |
| Side agreement (matched L/R panels) | 91.2% (n=34) | 96.8% (n=31) | 70.0% (n=30) | 70.0% (n=30) | 95.7% (n=23) | 95.5% (n=22) |
| Severity exact / within 1 / weighted kappa | 81.8% / 100% / 0.83 | 80.4% / 100% / 0.80 | 68.1% / 97.9% / 0.68 | 68.1% / 97.9% / 0.68 | 60.5% / 100% / 0.59 | 60.0% / 100% / 0.60 |
| Sev-3 panels found / at sev 3+ | 76.6% / 72.3% (n=47) | 75.0% / 70.5% (n=44) | 70.5% / 63.6% (n=44) | 70.5% / 63.6% (n=44) | 54.2% / 45.8% (n=48) | 52.3% / 43.2% (n=44) |
| Sev-4 panels found / rated 4 | 100% / 87.5% (n=8) | 100% / 87.5% (n=8) | 100% / 87.5% (n=8) | 100% / 87.5% (n=8) | 75.0% / **0%** (n=8) | 75.0% / **0%** (n=8) |
| Gate agreement (all 34 images) | 30/34 | - | 25/34 | - | 32/34 | - |
| Cost range high/low, median | 4.1x | - | 4.3x | - | 5.4x | - |
| Free-guess point outside engine range | 20% (3/15) | - | 30% (3/10) | - | 20% (4/20) | - |
| `request_more_photos` share (all 34) | 41.2% | - | 52.9% | - | 44.1% | - |
| Latency p50 / max, s (uncached, n=34; no p95, n < 100) | 13.8 / 20.5 | - | 4.8 / 11.2 | - | 9.2 / 16.9 | - |
| Cost per claim, extraction mean | $0.0338 | - | $0.0114 | - | $0.0011 | - |
| Repeatability: same routing / same max severity (10 × 3) | 70% / 90% | - | 90% / 100% | - | 100% / 90% | - |
| Cost at volume (ASSUMPTION: 10,000 claims/month, extraction only) | $338/mo | - | $114/mo | - | $11/mo | - |

Year has very small denominators (3-4): the labeler gave years for few images.

### F5 scoring fix: before / after (same saved runs)

The as-run harness stripped accented letters, so "Citroën" did not match the label "citroen" (eval_015). eval_v2 folds accents and case symmetrically for labels and predictions. Only make changed.

| Metric | Opus | Sonnet | Haiku |
|---|---|---|---|
| Make accuracy | 95.0% (19/20) -> **100% (20/20)** | 81.2% (13/16) -> **87.5% (14/16)** | 81.0% (17/21) -> **85.7% (18/21)** |
| Model accuracy | 82.4% -> 82.4% (unchanged) | 64.3% -> 64.3% | 44.4% -> 44.4% |
| Color accuracy | 96.3% -> 96.3% | 100% -> 100% | 96.4% -> 96.4% |

### Sensitivity: excluding the audited labels

Excluding eval_016, 017, 023, 029, 030 and 033 (see "Label audit"). Label files are not edited.

| Metric | Opus | Sonnet | Haiku |
|---|---|---|---|
| Make accuracy | 100% (16/16) | 91.7% (11/12) | 87.5% (14/16) |
| Model accuracy | **92.3% (12/13)** | 70.0% (7/10) | 46.2% (6/13) |
| Color accuracy | 95.7% (22/23) | 100% (17/17) | 95.7% (22/23) |
| Year range overlaps label | 100% (3/3) | 100% (2/2) | 100% (3/3) |

Model accuracy moves most (Opus 82% -> 92%): the audited eval_033 and eval_023 were scored as model-name misses for every model.

## Label audit (report only; no label file edited)

| Image | Label | Evidence it may be wrong | Effect |
|---|---|---|---|
| eval_033 | Nissan **Sunny** | Photographer's Commons title: "1990 Nissan **Bluebird** LX"; all three models said Bluebird (or unknown) | Scored as a model-name miss for Opus and Sonnet |
| eval_023 | Chery **Riich M1** | Title: "Chery **A1** after rear crash test" | Model-name denominator includes a likely-wrong label |
| eval_029 | years 1986-1990 | Title: "**Late 1991** Ford Escort mk4" | Year label excludes the titled year |
| eval_030 | 9 damage rows (fender/door dents sev 3, deformed bumper) on an "undamaged"-bucket car | The car looked worn and rusty in the contact-sheet review; whether these are claim damage or wear is unclear | Drives F6 (Haiku fast-track), now marked a disputed label |
| eval_016 | gate pass; Jeep Wrangler, hood sev 3 | Rainy street scene with a truck, a police car and a Jeep, damage small and far away; Opus and Sonnet refused it as `multiple_vehicles` / `damage_area_not_visible` | Counted as a gate miss for those models |
| eval_017 | gate pass; SEAT | Busy street: truck plus several parked cars; all three models refused it as `multiple_vehicles` | Counted as a gate miss for all three |

## Top error patterns

### Opus 5.5
- **Busy street scenes refused at the gate:** eval_004, eval_016, eval_017 (`multiple_vehicles` / `damage_area_not_visible`); labels say assessable, but 016 and 017 are audited labels.
- **Close-up passed that the labels reject:** eval_001 (shattered mirror glass, label `bad_angle_or_crop`).
- **Minor damage missed, then "no damage":** eval_024, eval_033, eval_034 routed to `request_more_photos` with no damage found. Safe direction, but eval_033's headlamp is labeled severity 3.
- **Side mirrored:** eval_003 (front door, quarter panel), eval_031 (front bumper).
- **Least repeatable routing:** 3 of 10 subset images changed outcome across 3 runs.

### Sonnet 5.5 (the app's current default; not changed)
- **Over-refusal at the gate:** 9 of 30 assessable images refused, mostly single parked cars with other cars in the background (eval_003, 004, 006, 026, 027, 028) plus eval_016, 017 (audited) and the close-up eval_035. Highest `request_more_photos` share (53%).
- **Side mirrored on 9 of 30 matched panels:** eval_002, 005, 008, 021, 031: F1 confirmed at scale.
- **Minor damage missed:** eval_024, eval_029, eval_033, eval_034 returned no damage.

### Haiku 5.5
- **Under-rates severity:** lower than the label on 13 of 38 matched panels; 0 of 8 severity-4 panels rated 4.
- **Fast-tracked eval_030** (F6): **disputed label** (see audit). Haiku saw severity 1-2 damage; the labels say severity-3 dents on an "undamaged"-bucket car. Opus and Sonnet did not fast-track it.
- **Misses panels:** recall 50% (eval_011, 015, 019, 022 each miss 2-4 labeled panels).
- **Model name "unknown" on 10 of 18**: cautious rather than wrong.
- **Slower than Sonnet** (p50 9.2 s vs 4.8 s) despite costing a tenth as much.

## Routing and abstention

| | Opus | Sonnet | Haiku |
|---|---|---|---|
| adjuster_review | 17 | 10 | 16 |
| request_more_photos | 14 | 18 | 15 |
| possible_total_loss | 2 | 4 | 0 |
| fast_track_candidate | 1 (eval_031) | 2 (eval_002, 031) | 3 (eval_002, 030, 035) |
| routing_v1.1 "better photos" note | 8 | 6 | 7 |

- The low-confidence route (`request_more_photos` on a photo that passed the gate) now has real cases: Opus eval_002 and eval_035, Sonnet eval_032, Haiku eval_031 and eval_032. This closes the item deferred in Phase 2.
- Most `request_more_photos` outcomes are "no damage found" on minor photos, or gate refusals: the system abstains rather than guesses, at the price of missing minor damage.

## Cost engine vs free-guess baseline

- When the engine gives a full range, the model's own point guess falls outside it 20-30% of the time.
- When the engine refuses to price (severity 4), the baseline still names a number: median $6,000 (Opus, 7 claims), $5,500 (Sonnet, 7), $9,000 (Haiku, 1).
- Engine ranges are wide by design (median high/low 4.1-5.4x). Whether real costs fall inside them is unmeasured.

## Limitations

- **Labels are one model's opinion, not human-verified, and not blind.** GPT-6.1 Sol-Light labeled the images after seeing a contact sheet that showed each image's bucket name. Agreement, not accuracy; errors shared by both models are invisible (side mirroring is the obvious candidate).
- **Known-suspect labels** (audit above): at least 2 contradict the photographers' titles (eval_033, eval_023), 1 year range excludes the titled year (eval_029), 1 is disputed damage vs wear (eval_030), 2 call busy street scenes assessable (eval_016, eval_017). The sensitivity table shows how far they move the vehicle metrics.
- **Scoring changed after viewing results, once (F5):** accent folding only, approved by the candidate, applied symmetrically; the as-run scores are kept and shown.
- **Small n:** 34 images; per-metric denominators 3-48. One image moves a percentage by 2-30 points. No confidence intervals; no p95 latency (n < 100).
- **Latency:** local machine, 3 models run in parallel; production latency was measured separately on Railway (Sonnet p50 about 5.7 s).
- **One effort level** (medium) for all models; not swept.
- **Cost accuracy:** N/A: no public ground truth.
