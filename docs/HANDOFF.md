# HANDOFF (facts for the README, eval write-up and deck)

Started in Phase 1 and filled in as facts are verified. The full handoff is completed in Phase 6.

## Decisions recorded so far

### Side (left/right) is reported and scored, but never priced

- **What:** every damage item carries `side` (the vehicle's own left/right/center/unknown). The eval scores side as its own metric (see docs/failures.md F1: Sonnet 5.5 mirrors sides, Opus 5.5 did not in 4/4 runs).
- **Cost table:** side is NOT a key. Per the FR4 spec, the table keys on panel class x operation x severity, plus a vehicle-class multiplier. A left fender and a right fender price the same.
- **Proof:** `tests/test_cost_engine.py::test_side_does_not_change_cost` flips every item's side and asserts low/mid/high are unchanged. Side IS used to tell parts apart (a left and a right fender are two parts, each priced once), never to set a price.
- **Why:** a side error should cost an adjuster a correction, not move the price. Side matters for parts ordering and supplements, which is why it is still measured.

### Cost shown as a range; mid is API-only

- The cost engine returns `low_usd`, `mid_usd` and `high_usd`. `mid_usd` is the arithmetic midpoint, labeled in the schema as "used for routing and eval only".
- **Phase 3 UI rule (candidate decision):** show a single range, low to high. Do not show mid.
- When any item is severity 4 (or on a pillar / unknown panel), the total is "cost not estimable" and only the priced subtotal is reported. The unpriced part has no upper bound we can defend.

### Wide-range rule (3x) kept, though currently redundant

- **Rule:** if high / low > 3, the claim goes to `adjuster_review` ("too uncertain to automate").
- **Currently redundant:** cost table v1 bands are deliberately wide, so every claim with a replacement (severity 3) item already exceeds 3x, and severity 3 is already excluded from fast track. With v1 numbers the rule never changes an outcome on its own.
- **Why it stays (candidate decision):** it guards the boundary independently of the severity rule. If the table is replaced by real estimating data with narrower bands, or the fast-track severity limit changes, uncertainty in the price still blocks automation.

### Cost ranges are bounds, not calibrated intervals

- low/high are the table's plausible bounds for the visible damage. They are not a statistical confidence interval, and how often real repair costs fall inside them has never been measured (no public ground truth; see the eval plan).
- **Missing cost drivers (not priced):** ADAS sensor recalibration, paint blending into adjacent panels, taxes, rental and towing, storage, sublet work, and EV-specific work (battery inspection, high-voltage safety procedures). Also returned in every estimate's caveats.
- Per-claim minimum: low (and high) are never below $100 per claim (assumption), applied once per claim, not per item.

### Region input

- `POST /api/claims` takes an optional `region` form field: `low_cost`, `standard` (default) or `high_cost`. It scales the $68/h labor rate by 0.85 / 1.00 / 1.25. The tiers and multipliers are assumptions with no source.

### LLM free-guess baseline

- A separate model call (`app/llm.py::guess_cost`, prompt `llm_baseline_v1`), run only when `include_llm_baseline=true` (API form field) or `LLM_BASELINE_ENABLED=true`. Off by default, and not shown in the main UI.
- Its number is never used for pricing or routing (`tests/test_api_wiring.py::test_baseline_never_changes_cost_or_routing`). It exists so the eval can compare the deterministic engine against "just ask the model".
- No baseline call is made when the photo check fails.

### Deferred Phase 2 checklist item: low-confidence case routed to request_more_photos

- **Status: DEFERRED (candidate decision, 2026-11-10).** No real image so far has passed the photo check with mostly low-confidence findings. Case 2 (Pohang) reached `request_more_photos` only by failing the photo check, and the candidate ruled that it does not count.
- **Covered by unit tests:** `tests/test_routing.py::test_mostly_low_confidence_minor_damage_requests_photos` and `::test_no_damage_found_requests_photos`.
- **Plan:** look for a real passing-photo, mostly-low-confidence case in the live runs and the Phase 4 eval set. Do not tune the prompt to produce one. If none appears by Phase 6, state it as untested on real data.
