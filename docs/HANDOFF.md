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
