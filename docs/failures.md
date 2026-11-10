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
- **Recurrence on case 7b (`runs/phase1/case7b_screenshot_cropped.json`), Sonnet 5.5:** front view of a BMW; the broken headlamp is on the viewer's right, which is the vehicle's LEFT. The model reported "right headlamp shatter" (and right/left fenders that are probably swapped too). **Confirmed by the candidate: the damaged headlamp is the vehicle's left.** The Phase 2 re-run repeated the error (right headlamp, right fender severity 4).
- **Status:** open on Sonnet: 3 of 5 distinct single-vehicle photos mirrored so far (F1 Altima, Cirrus, BMW), all confirmed by the candidate; Starex and Mercedes correct. The fix did not work for the provisional default model. Side accuracy is now a model-choice factor for the Phase 4 eval (side is scored separately). Demo use: run the same photo on Sonnet and Opus.

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

## Dataset skew note: DEV images are mostly severe crashes

- The Phase 1 DEV images skew toward severe damage (crushed front ends, a roof collapse, a pole impact). After the Phase 2 re-run **no case is routed to `fast_track_candidate`**, so the fast-track path has only been exercised by unit tests, never by a real photo.
- The low-confidence route (`request_more_photos` because most findings are low confidence) has also not fired on a real photo that passed the photo check.
- **Implication for Phase 4:** the eval set needs minor-damage images (scuffs, small dents, a single cracked lamp) and some ambiguous-but-passing photos. Otherwise the fast-track and low-confidence rules stay untested on real data.

## Phase 5: untested or unverified (2026-11-10)

Stated honestly so they can be raised in the demo; update as each is verified live.

- **Docker image never built.** Docker is not installed on the dev machine (not installed without asking). Replayed instead: a context with only what `.dockerignore` allows, the same frozen no-dev `uv sync`, and the exact CMD with env vars only. Not covered: the base image, the ghcr.io uv copy, the non-root user, Railway's builder.
- **Volume permissions for a non-root container on Railway: FAILED on first deploy, fixed (see F3).**
- **Railway proxy hop count:** `TRUST_PROXY_HOPS=1` assumes Railway's edge appends the real client IP as the last X-Forwarded-For entry. If that's wrong, per-IP limits either lump all users into one bucket (too strict) or trust a forgeable entry (too loose). Not verifiable from my side without the deployment.
- **Rate limits and the concurrency cap are in memory, per instance:** they reset on restart and would not hold with more than 1 replica (railway.json pins 1). The daily call and spend caps are in SQLite and do survive restarts.
- **Login brute-force protection is only a per-IP rate limit (10/min)**; no lockout, no CAPTCHA. A 24-character random code makes guessing impractical; a short code would not.
- **URL input from Railway:** the rehearsal fetched a Wikimedia image fine from a home IP with the generic User-Agent; from a datacenter IP Wikimedia may block it (it blocked a burst earlier, F-note in Phase 1). Set `URL_FETCH_USER_AGENT` if so.
- **Cold-start / deploy time: 40 s** from `git push` (19:26:01Z) to the first moment the NEW code served `/healthz` 200 and `/health` reported schema 1.3.0 (19:26:41Z), 2026-11-10, commit 9ea995e. Includes Railway's build (cached layers) and container start; polled every ~5 s. Railway keeps the old container serving until the new one is healthy, so users saw no downtime.
- **Daily call and spend caps: unit tests only, untested live.** The candidate skipped the live spend-cap demo (2026-11-10). Covered by `tests/test_limits.py` (call cap, spend cap, fail-closed ledger error, persistence across restart) and the local rehearsal; the live ledger is seen counting correctly in `/metrics` (`usage_today`), but no live refusal has been shown.

## F3: First Railway deploys failed at startup (config + volume permissions)

- **Date:** 2026-11-10, first Railway deploys.
- **Failure 1:** `Configuration error: DATA_DIR 'data' is not writable.` The Railway variable was set to `data` (the local-dev value from `.env.example`), which resolves to `/app/data`; the non-root user can't create it. Fix: `DATA_DIR=/data` (absolute). Fail-fast worked as designed: the app refused to start instead of running without a database.
- **Failure 2:** after the fix, `DATA_DIR '/data' is not writable.` Railway mounts the volume root-owned and the image ran as uid 10001 (`USER appuser`). This was listed as an untested risk before deploying.
- **Fix (candidate chose option A):** the container starts as root only to run `docker/entrypoint.py`, which chowns `DATA_DIR` to 10001 (never following symlinks), drops privileges permanently, refuses to continue if still root, and execs uvicorn. The app never runs as root. Rejected: running the whole container as root (simpler, weaker isolation); an unconfirmed Railway setting.
- **Verification:** root path unit-tested with recorded OS calls (`tests/test_entrypoint.py`); non-root path run for real locally. Live confirmation pending the redeploy.

## F4: Per-IP rate limit does not trigger on Railway (OPEN, deferred by the candidate)

- **Date:** 2026-11-10, live check (`runs/phase5/live_main_20261110T184705Z.json` and follow-up probes).
- **Expected:** with `RATE_LIMIT_CLAIMS_PER_MIN=6`, a burst of 8 claim requests from one client gets 429 from the 7th. It does locally (`tests/test_limits.py`, local rehearsal).
- **Actual (live):** 8/8 requests got through, three times: with `TRUST_PROXY_HOPS=0` (copied from `.env.example`), with `TRUST_PROXY_HOPS=1`, and with a fixed client-supplied `X-Forwarded-For`. `/metrics` showed no limit triggers.
- **What this shows:** Railway puts a per-request-varying value in the last `X-Forwarded-For` position (or replaces the header), so "rightmost entry = client" is wrong behind Railway's edge. Every request lands in its own bucket.
- **Side effect fixed along the way:** with `TRUST_PROXY_HOPS=0`, HSTS was also missing; with 1 it is present (Railway does send `X-Forwarded-Proto: https`).
- **Still protecting the key:** access code gate, concurrency cap, daily call and USD caps (SQLite, fail closed).
- **Re-test after `TRUST_PROXY_HOPS` was fixed (2026-11-10 19:27Z, commit 9ea995e):** 1 real claim then 8 claims reusing the same, now-cached photo (each passes the rate limiter, then is served from the image-hash cache: $0, no model call; ledger unchanged at 10 calls / $0.1716). All 9 got 200 within ~22 s against a limit of 6/min; no trigger. Still open; the setting was not changed on a guess.
- **Next step (approved later):** temporary log fields (count of XFF entries, salted hash per position, salted hash of `X-Real-IP`), one marked burst, read which position is stable; then `TRUST_PROXY_HOPS=2`, use `X-Real-IP`, or fall back to per-session limiting. Do not guess a hop count: trusting a forgeable entry would let clients bypass the limit.

## Live check notes (2026-11-10)

- Railway's edge adds `server: railway-hikari`, `x-railway-edge` and `x-railway-request-id` to every response. Not the app (which sends no Server header) and not secret; reveals only the hosting provider. Cannot be removed from the app.
- Two "timed" live runs were cache hits (photos already sent to this deployment by the candidate's own uploads), so the script's first latency summary was wrong. Model-call runs only: p50 about 5.7 s, max 7.6 s, n=6. The script now excludes cache hits from latency.

## Design decision (not a failure): rule order sends low-confidence severe claims to an adjuster

- **Observed:** `case8_multiphoto_mercedes_a.jpg` (wheel severity 4 / low, fender severity 3 / low; 2 of 2 low confidence) routes to `adjuster_review`, not `request_more_photos`.
- **Why, by design:** routing checks rule 4 (needs a human: any severity 4, or severity 3+ at low confidence, among others) before rule 5 (half or more low confidence -> ask for photos). Severe damage needs a person whatever the photos show; asking for photos first would only delay that person. Rule 5 decides only minor, uncertain claims, where a better photo could change the outcome, possibly to fast track.
- **Gap and fix:** the photo request was lost on severe, low-confidence claims. routing_v1.1 keeps the outcome and adds a secondary note naming the areas better photos would help with (see HANDOFF, "Routing v1.1").

## Phase 4 eval: not measurable or not measured (2026-11-10, commit 5015ec7)

- **Accuracy against real adjusters:** not measurable. Labels are one model's (ChatGPT) and not human-verified; all metrics are agreement.
- **Cost accuracy and range coverage:** N/A, no public ground truth repair costs.
- **p95 latency:** not reported (n = 34 per model; p95 needs n of 100 or more).
- **Statistical significance / confidence intervals:** not computed; n is too small to separate models on most metrics.
- **ChatGPT labeling model:** GPT-6.1 Sol-Light (recorded after the run; labels re-imported with only `label_source` changed).
- **Labeler was not blind:** the contact sheet with bucket names was uploaded in the first ChatGPT batch.
- **Effort sweep, multi-photo claims, HEIC input:** not in the eval set.

## F5: eval.py make normalization dropped accented letters (FIXED: scoring bug found after viewing results)

- **Found:** after the run, while reading misses. `eval.py` `norm()` stripped non-ASCII, so "Citroën" became "citron" and failed to match the label "citroen" (eval_015), costing every model one make point.
- **This was a scoring bug found AFTER viewing results.** Fixed with the candidate's approval as harness `eval_v2` (commit da68f67): symmetric Unicode normalization (NFKD, strip accents, casefold) for make, model and color, applied identically to labels and predictions. The SAVED runs were re-scored; no model was re-run; no prompt, schema, rubric or routing rule changed.
- **Before -> after (make accuracy):** Opus 95.0% -> 100% (20/20); Sonnet 81.2% -> 87.5% (14/16); Haiku 81.0% -> 85.7% (18/21). Model and color unchanged. As-run scores kept in `eval/results/5015ec7_20261110T194347Z/summary_v1_asrun.json` and `report_v1_asrun.md`.

## F6: Haiku fast-tracks a claim the labels call replacement-level (eval_030): DISPUTED LABEL

- **Input:** eval_030 (1976-era Honda Civic, labeled fender and door dents severity 3 and a deformed bumper).
- **Expected:** not `fast_track_candidate` (severity 3 blocks fast track).
- **Actual (Haiku 5.5):** findings at severity 1-2 with medium confidence, estimate $840-$2,110, routed `fast_track_candidate`. Opus and Sonnet did not fast-track it.
- **Why it matters:** the one case in the eval where a model under-rating severity moves a claim toward automation. Fast track is still a candidate only (a human approves payment), but it is the failure mode the routing rules exist to prevent.
- **Status: disputed label (candidate decision).** eval_030 is in the "undamaged" bucket, the car looked worn and rusty in the contact-sheet review, and whether the labeled "dents" are claim damage or wear is unclear. Neither the label nor Haiku's reading can be confirmed without a human. Listed in the label audit (`docs/eval_results.md`); excluded in the sensitivity view.

## F1 at scale: Sonnet side mirroring in the eval

- Sonnet 5.5 side agreement 70% (21/30 matched left/right panels), vs Opus 91% and Haiku 96%. Mirrored cases: eval_002, 005, 008, 021, 031.

## Sonnet over-refuses at the gate as `multiple_vehicles`

- 9 of 30 images the labels call assessable were refused by Sonnet, mostly single parked cars with other cars in the background (eval_026, 027, 028, 006, 003). Opus refused 3, Haiku 2.
