# Failure log

Every real failure found while building, each with input, expected and actual. "Expected" is the
builder's visual read confirmed by the candidate, unless it says otherwise; it is not an adjuster label.

| ID | Failure | Status |
|---|---|---|
| F1 | Side mirrored (vehicle left reported as right) | **Open** on Sonnet 5.5 (prompt fix did not work); Opus mostly correct |
| F2 | Cropped screenshot of a web photo passes the gate | **Open** (needs reverse-image search; out of scope) |
| F3 | First Railway deploys failed at startup (config, volume permissions) | Fixed |
| F4 | Per-IP rate limit does not trigger on Railway | **Open** (deferred by the candidate) |
| F5 | Eval scoring dropped accented letters | Fixed (scoring bug found after viewing results) |
| F6 | Haiku fast-tracks eval_030, labeled replacement-level | **Disputed label** |
| F7 | Completion card shows an override as "System recommended: <same route>" after a re-route | **Open** (fix on a branch, not deployed) |

## F1: Side mirrored (vehicle left reported as right)

- **Input:** `data/samples/altima_accident.jpg` (Wikimedia Commons "Altima-Accident.jpg", CC BY 3.0): front three-quarter view of a white Nissan Altima. claude-sonnet-5-5, effort medium. Smoke test request `5a1b559c`, 2026-11-10, prompt extract_v1.
- **Expected:** damage (fender, bumper cover, headlamp, wheel, door edge) on the vehicle's **left** (US driver side): the photo is taken from the front, the damaged side is on the viewer's right, and the steering wheel shows through the windshield on that side.
- **Actual:** all 6 damage items `side: right`; `not_assessable` lists "left side and rear of vehicle".
- **Why it matters:** wrong side means wrong parts ordered and a supplement later.
- **Fix attempted:** prompt extract_v2 / schema 1.1.0 added `camera_view` (filled before any side) and a worked example from a REAR view (the F1 image was deliberately not used). Regression on the F1 image: Sonnet **6/6 still wrong** (`camera_view: front_right`); Opus **4/4 correct** (`front_left`) (`data/runs/cache_experiment.txt`, `data/runs/opus_side_check.txt`, local only).
- **Recurrences (Sonnet, extract_v2, all confirmed by the candidate):**
  - Input `case1_clean_cirrus.jpg` / `case6_injection_cirrus.jpg` (requests `837b6ed4`, `9f94e4ef`): expected vehicle's left; actual `front_right`, "right headlamp".
  - Input `case7b_screenshot.png`: expected broken headlamp on the vehicle's left; actual "right headlamp shatter" (twice).
  - Correct on the Starex and the Mercedes pair. Builder's own error: the builder first called Mercedes photo B "front-left"; the model's `front_right` was right (confirmed by the candidate).
- **At scale (eval, commit 5015ec7):** Sonnet side agreement **70%** (21/30 matched left/right panels; mirrored on eval_002, 005, 008, 021, 031) vs Opus 91% and Haiku 96%.
- **Status: open** on Sonnet 5.5, the current default. Side is scored separately and never priced.

## F2: Cropped screenshot of a web photo passes the gate

- **Input:** `data/samples/case7b_screenshot.png`: the candidate's screenshot of a damaged BMW photo on a body shop's web page, cropped to the photo with no browser UI (not clean-licensed; local only). Sonnet, extract_v2, request `19c99af6`.
- **Expected:** gate fails as `likely_screenshot_or_stock` and asks for an original photo.
- **Actual:** gate passes (`status: ok`); full assessment: BMW 1 Series, 6 damage items, hood severity 4.
- **Contrast:** the same photo with the browser address bar visible (case 7, and the clean-licensed case 7c) is refused. The model detects screenshot chrome, not reuse of a published photo.
- **Status: open.** Not tuned (candidate instruction). Production path: reverse-image search, perceptual hashing against known images, EXIF/provenance checks.

## F3: First Railway deploys failed at startup

- **Input:** Railway deploys of commit 5c9d1c0 with a volume at `/data`.
- **Expected:** the app starts and `/healthz` returns `{"status":"ok","db":"writable"}`.
- **Actual 1:** `Configuration error: DATA_DIR 'data' is not writable.` The Railway variable was `data` (the local value from `.env.example`), which resolves to `/app/data`. Fixed by setting `DATA_DIR=/data`.
- **Actual 2:** `DATA_DIR '/data' is not writable.` Railway mounts the volume root-owned; the image ran as uid 10001. This was listed as an untested risk before deploying.
- **Fix (candidate chose option A, commit c6e05b9):** the container starts as root only to run `docker/entrypoint.py`, which chowns `DATA_DIR` to 10001 (never following symlinks), drops privileges for good, refuses to continue if still root, and execs uvicorn. Rejected: running the whole container as root; an unconfirmed Railway setting.
- **Status: fixed.** Live: "Application startup complete", `/healthz` writable, data survived a redeploy. The fail-fast check worked as designed both times.

## F4: Per-IP rate limit does not trigger on Railway

- **Input:** live deployment, `RATE_LIMIT_CLAIMS_PER_MIN=6`. Bursts of 8 claim requests from one client: (a) `TRUST_PROXY_HOPS=0`; (b) `TRUST_PROXY_HOPS=1`; (c) a fixed client-supplied `X-Forwarded-For`; (d) after the fix, 1 real claim + 8 cached re-sends on commit 9ea995e ($0, no model calls, ledger unchanged at 10 calls / $0.1716).
- **Expected:** 429 from the 7th request ("Too many requests from your network..."), as in the unit tests and the local rehearsal.
- **Actual:** every request got through, all four times (9 claims in ~22 s in run (d)); `/metrics` showed no limit triggers.
- **What it shows:** Railway puts a per-request-varying value in the last `X-Forwarded-For` position (or replaces the header), so "rightmost entry = client" is wrong behind Railway's edge.
- **Side effect fixed:** with `TRUST_PROXY_HOPS=0` HSTS was missing; with 1 it is present.
- **Still protecting the key:** access code, concurrency cap, daily call and USD caps (fail closed).
- **Status: open (deferred by the candidate; mentioned verbally in the demo).** Next step: log hashed forwarded-address positions for one marked burst and read which is stable. The setting was not changed on a guess.

## F5: Eval scoring dropped accented letters

- **Input:** eval_015 (Citroën). Label make "citroen"; Opus, Sonnet and Haiku all answered "Citroën".
- **Expected:** a match.
- **Actual (eval_v1, as run):** scored as a miss for every model, because `norm()` stripped non-ASCII ("Citroën" -> "citron").
- **This was a scoring bug found AFTER viewing results.** Fixed with the candidate's approval as harness `eval_v2` (commit da68f67): symmetric Unicode normalization (NFKD, strip accents, casefold) for make, model and color. The SAVED runs were re-scored; no model re-run; no prompt, schema, rubric or rule changed.
- **Before -> after (make accuracy):** Opus 95.0% -> 100% (20/20); Sonnet 81.2% -> 87.5% (14/16); Haiku 81.0% -> 85.7% (18/21). Model and color unchanged. As-run scores kept in `eval/results/5015ec7_20261110T194347Z/summary_v1_asrun.json`.
- **Status: fixed.**

## F6: Haiku fast-tracks eval_030, labeled replacement-level

- **Input:** eval_030 (1970s Honda Civic, "undamaged" bucket). Labels: fender and door dents severity 3, deformed bumper, 9 rows.
- **Expected (per labels):** not `fast_track_candidate` (severity 3 blocks fast track).
- **Actual (Haiku 5.5, run 5015ec7):** findings at severity 1-2, medium confidence; $840-$2,110; `fast_track_candidate`. Opus and Sonnet did not fast-track it.
- **Why it matters:** the only eval case where a model under-rating severity moves a claim toward automation (fast track is still a candidate; a human approves payment).
- **Status: disputed label (candidate decision).** The car looks worn and rusty; whether the "dents" are claim damage or wear can't be settled without a human. In the label audit; excluded in the sensitivity view.

## F7: Completion card names the re-routed recommendation in an override

- **Input:** live claim `ad50b973` (eval_031), 2026-11-12, commit 47ffac7. System recommended Fast-track candidate. The adjuster changed a severity 2 -> 3 (which re-routes the claim to Adjuster review) and chose final route Adjuster review with a reason.
- **Expected:** the card says the adjuster overrode Fast-track candidate (the stored recommendation; the server compares the final route with it, so this is an override).
- **Actual:** "Final route: Adjuster review. Adjuster override. System recommended: Adjuster review" (the override panel says the same): it names the re-routed recommendation, so it reads like an override of a route by itself. Stored data and the Review history ("Fast-track candidate -> Adjuster review") are correct.
- **Cause:** the card and the override panel use `routing.outcome` (after re-routing) instead of `system_route`.
- **Status: open.** Display-only fix prepared on a branch (not deployed).

## Other findings at scale (eval, run 5015ec7)

- **Sonnet over-refuses at the gate:** input: 30 images the labels call assessable. Expected: assessed. Actual: 9 refused, mostly single parked cars with other cars in the background flagged `multiple_vehicles` (eval_003, 004, 006, 026, 027, 028; also eval_016, 017 (audited labels) and close-up eval_035). Opus refused 3, Haiku 2.
- **Haiku under-rates severity:** input: 8 labeled severity-4 panels. Expected: severity 4. Actual: 0 of 8 rated 4; lower than the label on 13 of 38 matched panels.
- **Minor damage missed:** input eval_024, 033, 034 (bumper scuff, broken headlight, bumper scratches). Expected: damage found. Actual: "no damage found" -> `request_more_photos` for Opus and Sonnet (safe direction).

## To review (not classified as a failure)

- **R1: BMW hood rated severity 4 (case 7b).** Input `case7b_screenshot.png`; expected per the rubric: a buckled hood alone is usually severity 3; actual: `center hood deformation`, severity 4. Over-calls cost adjuster time, not money. Candidate to review.

## Design decision (not a failure): rule order sends low-confidence severe claims to an adjuster

- `case8_multiphoto_mercedes_a.jpg` (wheel severity 4 / low, fender severity 3 / low) routes to `adjuster_review`, not `request_more_photos`: rule 4 (needs a human) runs before rule 5 (ask for photos), because severe damage needs a person whatever the photos show. The photo request was lost; routing_v1.1 restores it as a secondary note without changing the outcome.

## Known limitations

- **Stock-photo detection** from pixels alone is unreliable (see F2).
- **DEV images skew severe;** the eval set added minor damage. Fast track and the low-confidence route now have real eval cases.
- **Railway's edge adds** `server: railway-hikari`, `x-railway-edge`, `x-railway-request-id` to every response: not the app, not secret.

## Not measured or untested

- **Accuracy against adjusters:** not measurable; labels are one model's (GPT-6.1 Sol-Light), not human-verified, and not blind (contact sheet with bucket names uploaded to the labeler).
- **Cost accuracy and range coverage:** N/A, no public ground truth.
- **p95 latency:** not reported (n = 34 per model in the eval, n = 6-8 live; needs n of 100+).
- **Confidence intervals / significance:** not computed.
- **Docker image:** never built locally (Docker not installed); replayed with the same frozen sync and CMD; Railway's build is the only full build.
- **Daily call and spend caps live:** unit tests and local rehearsal only; the candidate skipped the live demo. The live ledger counts correctly in `/metrics`.
- **Rate limits and concurrency cap** are in memory per instance (railway.json pins 1 replica).
- **Login brute force:** only a per-IP limit (and F4 means it isn't effective behind Railway); a 24+ character code makes guessing impractical.
- **Effort sweep, multi-photo claims in the eval, HEIC input:** not covered.
- **Cold start from a fully idle container:** not measured; push-to-healthy deploy time is 40 s.
