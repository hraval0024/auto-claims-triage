# Failure log

Every real failure found while building, with input, expected, and actual. "Expected" is the
builder's visual read of the photo unless it says otherwise; it is not an adjuster label.

## F1: Side mirrored (vehicle left reported as right)

- **Date / run:** 2026-11-10, Phase 1 smoke test, request `5a1b559c-0bff-4e3a-b71b-8a30535f5796`
- **Model / prompt:** claude-sonnet-5-5, effort medium, extract_v1 (draft rubric)
- **Input:** `samples/SOURCES.md#altima_accident` (Wikimedia Commons "Altima-Accident.jpg", CC BY 3.0). Front three-quarter view of a white Nissan Altima.
- **Expected:** the damage (fender, bumper cover, headlamp, wheel, door edge) is on the vehicle's **left** (US driver side). Evidence: the photo is taken from the front, the damaged side is on the viewer's right, and the steering wheel is visible through the windshield on that side.
- **Actual:** all 6 damage items reported as `side: right`; `not_assessable` lists "left side and rear of vehicle", so the model treated the visible side as the right.
- **Why it matters:** wrong side means wrong parts ordered and a supplement later. The rubric already defines side from the vehicle's point of view, and the model still mirrored it.
- **Status:** open. Candidate fixes to test: add a worked example to the rubric ("photo of the front: the vehicle's left is on the viewer's right"); ask the model to state which end of the car faces the camera before assigning sides; score side separately in the eval (planned).

## Known limitation (not yet observed): stock-photo detection

Detecting a stock or press photo from pixels alone is unreliable: a well-lit original photo and a stock image can look alike. The `likely_screenshot_or_stock` verdict is a weak signal. Real fraud checks would use reverse-image search and metadata, which are out of scope.
