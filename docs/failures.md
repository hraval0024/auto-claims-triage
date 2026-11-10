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
- **Case #8 (Mercedes C180, 2 photos), Opus 1 run:** photo A `rear_right`, photo B `front_right`, all damage on the right front. The two photos agree. Builder's correction: in the Phase 1 case table I had called photo B "front-left". A car facing the image's right shows its RIGHT side, so the model was right and the builder made the viewer-side mistake. **Confirmed by the candidate.**
- **Side stays its own metric** in the Phase 4 eval, separate from panel and damage type.
- **Recurrence in the Phase 1 run, 2026-11-10 (`runs/phase1/case1_clean.json`, `case6_injection.json`), Sonnet 5.5, extract_v2:** on the Chrysler Cirrus photo the car's front faces lower-left and its visible side faces the camera, which makes it the vehicle's LEFT. Both runs gave `camera_view: front_right`, a "right headlamp", and listed "left side of the front end" as not assessable, so the side is mirrored again. The same run got the Starex (`front_left`) and the Mercedes pair (`front_right`) right. **Side read confirmed by the candidate.**
- **Recurrence on case 7b (`runs/phase1/case7b_screenshot_cropped.json`), Sonnet 5.5:** front view of a BMW; the broken headlamp is on the viewer's right, which is the vehicle's LEFT. The model reported "right headlamp shatter" (and right/left fenders that are probably swapped too). Builder's read; candidate to verify.
- **Status:** open on Sonnet: 3 of 5 distinct single-vehicle photos mirrored so far (F1 Altima, Cirrus, BMW); Starex and Mercedes correct. The fix did not work for the provisional default model. Side accuracy is now a model-choice factor for the Phase 4 eval (side is scored separately). Demo use: run the same photo on Sonnet and Opus.

## F2: Cropped screenshot of a web photo passes the gate

- **Date / run:** 2026-11-10, Phase 1 case 7b, request `19c99af6-2235-4af1-8af9-dcfd9b93d640`
- **Model / prompt:** claude-sonnet-5-5, effort medium, extract_v2
- **Input:** `data/samples/case7b_screenshot.png`. The candidate's screenshot of a damaged BMW photo on a body shop's web page, cropped to the photo itself with no browser UI. Not clean-licensed; local only.
- **Expected:** `likely_screenshot_or_stock` (it is a screenshot of a published web photo) and a request for an original photo.
- **Actual:** the gate passed (`status: ok`) and returned a full assessment: BMW 1 Series, 6 damage items, hood severity 4.
- **Contrast:** case 7 (the same photo with the browser address bar and site header visible) was caught. The model detects screenshot *chrome*, not the reuse of a published photo.
- **Why it matters:** a reused web photo is a classic fraud pattern. This confirms the known limitation below; it is not fixable by prompt alone.
- **Status:** open. Not tuned (candidate instruction: report the verdict, don't tune to pass). Production path: reverse-image search, perceptual-hash matching against known images, and EXIF/provenance checks, all out of scope here.

## Known limitation: stock-photo detection

Detecting a stock or press photo from pixels alone is unreliable: a well-lit original photo and a stock image can look alike. The `likely_screenshot_or_stock` verdict catches visible screenshot UI (case 7) but not a cropped web photo (F2). Real fraud checks would use reverse-image search and metadata, which are out of scope.

## To review (not classified as failures yet)

### R1: BMW hood rated severity 4 (case 7b)

- **Run:** 2026-11-10, request `19c99af6-2235-4af1-8af9-dcfd9b93d640`, claude-sonnet-5-5, extract_v2.
- **Input:** `data/samples/case7b_screenshot.png` (front view of a BMW with the hood buckled and lifted).
- **Output:** `center hood deformation`, severity 4 (medium confidence). The rubric reserves level 4 for damage reaching structure or safety systems; a buckled hood alone would usually be level 3 (replace).
- **Why it matters:** severity 4 makes the claim "cost not estimable" and sends it to a human, so an over-call costs adjuster time, not money.
- **Status:** to review by the candidate. Not a bug until the candidate decides. Note: this image is being replaced by a CC-licensed screenshot, so the case may need re-running.
