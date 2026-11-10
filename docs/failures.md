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
- **Fix attempted (prompt extract_v2, schema 1.1.0):** a per-photo `camera_view` field filled before any side, plus a worked example from a REAR view (the F1 image was deliberately not used, so F1 stays a clean regression check).
- **Regression result, 2026-11-10 (`data/runs/cache_experiment.txt`):**
  - claude-sonnet-5-5, effort medium, extract_v2: **6/6 runs still wrong**. All gave `camera_view: front_right` with sides `right` (one run also had a `left` item). The model misreads which side is visible; it isn't a mapping slip after a correct view.
  - claude-opus-5-5, effort medium, extract_v2: **1/1 correct** (`camera_view: front_left`, all sides `left`). n=1.
- **Opus follow-up, 2026-11-10 (`data/runs/opus_side_check.txt`):** claude-opus-5-5, effort medium, extract_v2, 3 more runs on F1: **3/3 correct** (`front_left`, all sides `left`). Opus total on F1: **4/4**. Severities stable across runs (fender/wheel 4; bumper/headlamp/hood 3; front door 3 or 4).
- **Case #8 (Mercedes C180, 2 photos), Opus 1 run:** photo A `rear_right`, photo B `front_right`, all damage on the right front. The two photos agree. Builder's correction: in the Phase 1 case table I had called photo B "front-left". A car facing the image's right shows its RIGHT side, so the model was right and the builder made the viewer-side mistake. Candidate to verify.
- **Side stays its own metric** in the Phase 4 eval, separate from panel and damage type.
- **Recurrence in the Phase 1 run, 2026-11-10 (`runs/phase1/case1_clean.json`, `case6_injection.json`), Sonnet 5.5, extract_v2:** on the Chrysler Cirrus photo the car's front faces lower-left and its visible side faces the camera, which makes it the vehicle's LEFT. Both runs gave `camera_view: front_right`, a "right headlamp", and listed "left side of the front end" as not assessable, so the side is mirrored again. The same run got the Starex (`front_left`) and the Mercedes pair (`front_right`) right. Builder's read; candidate to verify.
- **Status:** open on Sonnet: 2 of 4 distinct single-vehicle photos mirrored so far. The fix did not work for the provisional default model. Side accuracy is now a model-choice factor for the Phase 4 eval (side is scored separately). Demo use: run the same photo on Sonnet and Opus.

## Known limitation (not yet observed): stock-photo detection

Detecting a stock or press photo from pixels alone is unreliable: a well-lit original photo and a stock image can look alike. The `likely_screenshot_or_stock` verdict is a weak signal. Real fraud checks would use reverse-image search and metadata, which are out of scope.
