# Eval results: Phase 4

**Read this first.** Labels come from a single independent model (ChatGPT, model not recorded,
labeled 2026-11-10) and are **not human-verified**. Every number below is **agreement with that
model's labels, not accuracy against adjusters.** Where both models make the same mistake, it
scores as correct. The set is small (n = 34).

- **Commit evaluated:** `5015ec7` (prompt extract_v2, schema 1.3.0, rules routing_v1.1, cost_table_v1, effort medium)
- **Run:** `eval/results/5015ec7_20261110T194347Z/` (`runs.jsonl` raw outputs, `summary.json`, `report.md`)
- **Data:** 34 Wikimedia Commons photos (`eval/manifest.json`; 18 minor, 9 moderate/severe, 7 undamaged buckets); no overlap with DEV images (`eval/dev_overlap_check.txt`)
- **How:** the app's own pipeline (`app.pipeline.run_claim`), image-hash cache OFF, local (the deployed caps and ledger untouched). The LLM free-guess baseline is called separately on the main pass. Repeatability: 10 fixed images × 3 runs per model.
- **Spend:** $2.98 (Opus $2.17, Sonnet $0.73, Haiku $0.07), 162 claim runs, 0 exceptions.
- **Cost accuracy:** N/A: no public ground truth.

## Summary (as run)

| Metric (denominator) | Opus 5.5 | Sonnet 5.5 | Haiku 5.5 |
|---|---|---|---|
| Gate agreement (all 34 images) | **30/34** | 25/34 | **32/34** |
| Make accuracy (both-pass, label known) | **95.0%** (19/20) | 81.2% (13/16) | 81.0% (17/21) |
| Model accuracy (both-pass, label known) | **82.4%** (14/17) | 64.3% (9/14) | 44.4% (8/18) |
| Color accuracy | 96.3% (26/27) | 100.0% (21/21) | 96.4% (27/28) |
| Panel precision / recall (per-image sets) | **90.2% / 73.3%** | 81.0% / 67.1% | 90.5% / 50.0% |
| Damage-type precision / recall | 81.4% / 55.6% | 79.5% / 54.4% | 78.9% / 46.9% |
| Side agreement (matched panels, label L/R) | 91.2% (n=34) | **70.0%** (n=30) | 95.7% (n=23) |
| Severity exact / within 1 / weighted kappa (matched panels) | **81.8% / 100% / 0.83** | 68.1% / 97.9% / 0.68 | 60.5% / 100% / 0.59 |
| Sev-3 panels found / at sev 3+ | 76.6% / 72.3% (n=47) | 70.5% / 63.6% (n=44) | 54.2% / 45.8% (n=48) |
| Sev-4 panels found / rated sev 4 | 100% / 87.5% (n=8) | 100% / 87.5% (n=8) | 75.0% / **0%** (n=8) |
| Cost range high/low, median (full ranges) | 4.1x | 4.3x | 5.4x |
| Free-guess point outside engine range | 20% (3/15) | 30% (3/10) | 20% (4/20) |
| `request_more_photos` share (all 34) | 41.2% | 52.9% | 44.1% |
| Latency p50 / max, s (uncached, n=34; p95 not reported, n < 100) | 13.8 / 20.5 | **4.8 / 11.2** | 9.2 / 16.9 |
| Cost per claim, extraction mean | $0.0338 | $0.0114 | **$0.0011** |
| Repeatability: same routing / same max severity (10 images × 3) | 70% / 90% | 90% / 100% | 100% / 90% |
| Cost at volume (ASSUMPTION: 10,000 claims/month, extraction only) | $338/month | $114/month | $11/month |

Denominators differ by model because each metric only counts images both the labels and that model let through the gate (Opus 27, Sonnet 21, Haiku 28 of 34).

**Known scoring bug (not fixed, pending approval):** make matching turns "Citroën" into "citron", so eval_015 is scored as a miss for all three models although each said Citroën, as the label does. With accents folded, make accuracy would be 100% (20/20) Opus, 87.5% (14/16) Sonnet, 85.7% (18/21) Haiku. The table above is as run.

## Top error patterns

### Opus 5.5
- **Gate passes a close-up the labels reject:** eval_001 (shattered mirror glass, label `bad_angle_or_crop`) was assessed.
- **Busy street scenes refused:** eval_004, eval_016, eval_017 failed the gate as `multiple_vehicles` / `damage_area_not_visible`; labels say assessable. Arguably the model is right (the bucket review in Phase 4 prep flagged these as busy scenes).
- **Minor damage missed, then "no damage":** eval_024, eval_033, eval_034 (bumper scuff, broken headlight, bumper scratches) routed to `request_more_photos` with no damage found. Safe direction, but the eval_033 headlamp is labeled severity 3.
- **Side mirrored:** eval_003 (front door and quarter panel), eval_031 (front bumper).
- **Repeatability:** routing differed across 3 runs on 3 of 10 images: the highest variance of the three models.

### Sonnet 5.5 (the app's current default)
- **Over-refusal at the gate: 9 of 30 assessable images refused, almost all as `multiple_vehicles`**: eval_003, 004, 006, 016, 017, 026, 027, 028 (single parked cars with other cars in the background) and eval_035 (close-up). This alone explains its lower gate agreement and the highest `request_more_photos` share (53%).
- **Side mirrored on 9 of 30 matched panels:** eval_002 (doors), eval_005, eval_008 (headlamp, bumper), eval_021 (headlamp, fender, wheel), eval_031: F1 confirmed at scale.
- **Minor damage missed:** eval_024, eval_029, eval_033, eval_034 returned no damage.
- **Abstains on make/model:** eval_019 and eval_023 make "unknown".

### Haiku 5.5
- **Under-rates severity:** model lower than label on 13 of 38 matched panels (higher on 2); **0 of 8 severity-4 panels rated 4**; sev-3 recall 46%.
- **Unsafe fast-track:** eval_030 fast-tracked (fender, door, hood at severity 1-2) where labels have severity-3 dents and a deformed bumper. The only fast-track of a claim the labels call replacement-level.
- **Misses panels:** recall 50% (eval_011, 015, 019, 022 each miss 2-4 labeled panels).
- **Model name "unknown" on 10 of 18:** cautious rather than wrong (make accuracy holds at 81%).
- **Slower than Sonnet** (p50 9.2 s vs 4.8 s) despite being 10× cheaper.

### Where the labels are probably wrong
- eval_033: all three models said **Bluebird**; the label says Sunny; the photographer's Commons title says **1990 Nissan Bluebird**. Scored as a miss for every model.
- eval_023: label "Riich M1"; Commons title "Chery A1"; models said unknown.
- eval_015: label C5; Opus says Xsara Break, Sonnet Xsara Picasso. Unresolved.

## Routing and abstention

| | Opus | Sonnet | Haiku |
|---|---|---|---|
| adjuster_review | 17 | 10 | 16 |
| request_more_photos | 14 | 18 | 15 |
| possible_total_loss | 2 | 4 | 0 |
| fast_track_candidate | 1 (eval_031) | 2 (eval_002, eval_031) | 3 (eval_002, eval_030, eval_035) |
| routing_v1.1 "better photos" note | 8 | 6 | 7 |

- The low-confidence route (`request_more_photos` on a photo that passed the gate) now has real cases: Opus eval_002 and eval_035, Sonnet eval_032, Haiku eval_031 and eval_032. This closes the item deferred in Phase 2.
- `request_more_photos` is mostly "no damage found" on minor photos and gate refusals: the system abstains rather than guesses, at the price of missing minor damage.

## Cost engine vs free-guess baseline

- When the engine gives a full range, the model's own point guess falls outside it 20-30% of the time.
- When the engine refuses (severity 4, "not estimable"), the baseline still names a number: median $6,000 (Opus, 7 claims), $5,500 (Sonnet, 7), $9,000 (Haiku, 1).
- Engine ranges are wide by design (median high/low 4.1-5.4x). Whether real costs fall inside them is unmeasured (no ground truth).

## Limitations

- **Labels are one model's opinion, not human-verified.** Agreement, not accuracy. Shared errors (e.g. side mirroring) are invisible.
- **Label provenance issues:** the ChatGPT model and version were not recorded; the contact sheet (showing bucket names) was in ChatGPT's batch 1 with eval_027-035; at least 2 labels contradict the photographers' titles (eval_033, eval_023) and eval_029's year range excludes the titled 1991.
- **Small n:** 34 images; per-metric denominators 14-48. One image moves a percentage by 2-7 points. No confidence intervals reported; no p95 latency (n < 100).
- **Gate disagreements are ambiguous:** several "multiple vehicles" refusals are on busy street photos where refusing is defensible.
- **Latency:** local machine to the Anthropic API, 3 models run in parallel; production latency was measured separately on Railway (Sonnet p50 about 5.7 s).
- **Single effort level** (medium) for all models; effort and thinking depth were not swept.
- **Cost accuracy:** N/A: no public ground truth.
