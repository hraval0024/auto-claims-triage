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

### Human in the loop: review endpoint and corrections log (Phase 3)

- `POST /api/claims/{request_id}/review` takes `decision` (accept/reject) plus the adjuster's version of the vehicle, damage items (with `orig_index`, `removed`, or new items), summary, not-assessable list and region.
- **Originals come from the stored result**, not from the client: `app/store.py` saves each ClaimResult (no image bytes, no raw model output, no URLs) in SQLite at `data/app.db`. `app/review.py` diffs against it and writes one corrections row per changed field: field, original, corrected, timestamp, request id. Dropping an item without marking it `removed` is rejected (422).
- On accept, the claim is re-priced and re-routed from the corrected items; items set by an adjuster count as high confidence. A reject logs the decision without re-pricing.
- `GET /api/corrections` returns the log; the UI shows it. This log is eval data.
- **Production difference:** on Railway the filesystem is wiped on redeploy, so `data/app.db` needs a volume (details pending from the candidate). A real deployment would use a managed database and add reviewer identity (no auth in scope).

### UI (Phase 3)

- One page (`app/static/`, no build step) served by the same FastAPI app at `/`.
- Cost is shown as one range, low to high; `mid_usd` is never displayed. Severity-4 claims show "Cost not estimable" plus the partial range labeled "partial, excludes severity-4 items".
- The LLM baseline appears only if the server flag `LLM_BASELINE_ENABLED` is on; the UI never asks for it.
- Every model-derived string is inserted as text (`textContent`), never as HTML, so text read from a photo can't inject markup (`tests/test_review.py` checks app.js has no `.innerHTML`).

### Eval set and labeling (Phase 4 prep)

- 34 real Wikimedia Commons images (`eval/manifest.json`: id, title, link, license, author, sha256). Files live in `data/eval/` (gitignored), fetched by `scripts/fetch_eval.py`. eval_007 was dropped (off-topic burned-out shell; id not reused) and eval_031-035 were added (clean single-vehicle minor damage). None match a DEV image by sha256 or perceptual hash (`scripts/check_eval_overlap.py` -> `eval/dev_overlap_check.txt`).
- **Label provenance (candidate decision, 2026-11-10): ChatGPT only, one CSV set, no second labeler, no human adjudication.** Every imported row carries `label_source` stating it is model-generated and not human-verified. Consequences to state in the eval write-up:
  - Metrics are agreement with ChatGPT's labels, not accuracy against ground truth.
  - Shared failure modes are invisible: where both models make the same mistake (side mirroring, F1, is the obvious candidate), the eval scores Claude as correct.
  - Make/model has a partial independent check available: Commons titles and descriptions were written by the photographers and are hidden from ChatGPT (not built; see open questions).
- Prompt: `eval/labels/chatgpt_prompt.md` (image only, exact vocabulary, approved rubric definitions, output the two CSVs only; no titles, sources or model output).
- Import: `scripts/import_labels.py` validates every value against the schema (`scripts/label_schema.py`, documented in `eval/labels/VOCAB.md`), reports bad rows instead of fixing them, trims whitespace only (announced), and rejects a whole image if any of its rows is invalid. It writes `eval/labels/images_labels.csv`, `damage_labels.csv` and `import_report.txt`.
- Schema change: `gate_expected` was replaced by `should_pass_gate` (yes/no) + `gate_reason` (a blocking gate code when no; empty or `embedded_instruction_text` when yes). `has_visible_damage` is now yes/no.
- `labeler/` (local page) is kept only schema-compatible; not used for the ChatGPT labels.

### Hardening and deploy (Phase 5)

- Access: shared `APP_ACCESS_CODE` on every route except `/healthz`/`/login` (header for scripts, HMAC session cookie for the UI; constant-time compare; rotating the code ends all sessions). No auth/identity beyond that, by scope.
- Cost protection: per-IP rate limits, concurrency cap, daily model-call and USD caps in a SQLite ledger (fail closed), image-hash cache, idempotency keys. Every trigger logged and counted in `/metrics`.
- Ops: JSON logs with request id (no images, key, code or full URLs); `/healthz` (DB writable, no model call); `/metrics`; fail-fast config; `DATA_DIR` volume. Details and the Dockerfile review: `docs/DEPLOY.md`. Secrets scan: `docs/secrets_scan.txt`.
- **Where production would differ:** a queue and worker pool in front of the model call (today the HTTP request blocks for 5-15 s); a shared store (Redis) for rate limits and concurrency across replicas; a provider-side budget/rate-limit per tenant; Postgres instead of SQLite; real authentication with per-user audit identity.
