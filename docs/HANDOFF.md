# HANDOFF (facts for the README, eval write-up and deck)

Started in Phase 1 and filled in as facts are verified. The full handoff is completed in Phase 6.

## Decisions recorded so far

### Side (left/right) is reported and scored, but never priced

- **What:** every damage item carries `side` (the vehicle's own left/right/center/unknown). The eval scores side as its own metric (see docs/failures.md F1: Sonnet 5.5 mirrors sides, Opus 5.5 did not in 4/4 runs).
- **Cost table:** side is NOT a key. Per the FR4 spec, the table keys on panel class x operation x severity, plus a vehicle-class multiplier. A left fender and a right fender price the same.
- **Status of the proof:** the cost engine does not exist yet (Phase 2). When it is built, a unit test will assert that flipping `side` leaves the estimate unchanged. Until that test exists, "side doesn't affect cost" is a design statement, not a verified one.
- **Why:** a side error should cost an adjuster a correction, not move the price. Side matters for parts ordering and supplements, which is why it is still measured.
