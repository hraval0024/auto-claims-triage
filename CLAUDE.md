# CLAUDE.md: Vehicle Damage Claims Triage Prototype

## 0. Who is who

**I am the candidate.** I'm a Solutions Architect candidate for Scale AI doing this take-home. I will demo the prototype live to a panel playing a customer's leadership team (VP Engineering, claims business owner, data and risk owner). They will interrupt, push back, and ask what breaks at volume. I own every design decision and I must be able to defend every file you write.

**You are my build partner.** You write the code, run it, test it, and deploy it, under my direction. The architecture, scope, and tradeoffs in this document are my decisions. If you think one is wrong, tell me before building it (Section 6). Don't silently substitute your own judgment, and don't silently stop at a shortcut.

**Your scope is the working prototype only.** You do NOT write the README, the written evaluation approach, or the customer deck. I write those myself, because they are what I am being assessed on. You DO produce `docs/HANDOFF.md` (Section 9) with the raw facts I need to write them. Do not stop at "it compiles": run everything and show me real output.

---

## 1. The scenario

A large auto insurance carrier processes a high volume of vehicle damage claims and wants to know whether AI can help.

The prototype must accept a photograph of a damaged vehicle (upload or URL) and return:
1. Vehicle metadata: make, model, color
2. Damage summary, e.g. "left rear bumper dent with scratching"
3. Estimated repair cost, a rough estimate, delivered as a **range** (low / mid / high), not a point value

The AI reads the photo and extracts the damage; a deterministic table prices it (FR4). That is how the cost range stays "AI-generated" without making the LLM the source of the number. Do not turn the LLM back into the price source.

A user must be able to submit an image and get results back, from a deployed link.

## 2. Product framing (do not drift from this)

- **Business problem:** the first human look at a claim's photos is slow, inconsistent between adjusters, and capacity-bound. Simple claims wait in the same queue as complex ones.
- **What the carrier wants to change:** faster first response, more adjuster capacity for complex claims, consistent first assessments, less leakage and fewer supplements, better customer experience.
- **Reframe:** the goal is not "AI estimates repair cost." It is "decide the right next step for every claim within minutes, and be honest when the photos don't support a decision." The cost estimate is an input to routing, never a payout decision.
- **Boundary:** the system never decides coverage, liability, denial, or payment. A human stays in the loop for anything uncertain. Say this in the UI.

## 3. Functional requirements

**FR1 Input.** Single image by upload or URL. Support multiple photos per claim (merge findings; flag conflicting findings between photos).

**FR2 Quality gate (runs before extraction).** Structured verdicts: not a vehicle, multiple vehicles, too blurry or dark, damage not visible, bad angle or crop, likely screenshot or stock photo, text embedded in the image that looks like instructions. A failed gate returns a reason and what photo to send instead. It never returns a made-up assessment.

**FR3 Extraction (vision model, structured output).**
- Vehicle: make, model, color, year range. Each field has a confidence and may be `unknown`. Unknown is a valid, preferred answer over a guess.
- Damage items (list): panel/location, damage type (dent, scratch, crack, shatter, deformation, missing part, etc.), severity 1-4, confidence.
- Plain-language summary of the damage.
- "Not visible / cannot assess" list (e.g. underbody, structural, airbags).

**FR4 Cost engine (hybrid, deterministic).**
- The LLM does NOT output the final cost. It extracts damage items; a deterministic table (panel x damage type x severity -> parts cost band + labor hours) with a configurable regional labor rate produces a **low / mid / high range**.
- The table is a clearly labeled stand-in for real estimating data (CCC / Mitchell / Audatex). Every number in it is an assumption, marked as such in code and in the API response. Do not present it as real pricing.
- **Table spec (I set the inputs; you build the file):**
  - Structure: panel class x operation (repair / refinish / replace) x severity (1-4) -> body labor hours, refinish hours, paint/materials, parts price band; plus a vehicle-class multiplier (economy, mainstream, luxury/truck).
  - Stored as a versioned YAML or CSV file, not hard-coded in Python.
  - Every row has `source` and `confidence` columns. A value with no real source is tagged `assumption` with `confidence: low`. Never fill a value from memory and leave it untagged.
  - **Labor rate:** use body-shop rates, not general mechanical repair rates. Default body labor rate is about $68/hour (2026 "Who Pays for What?" survey median for non-DRP body work), configurable by region. Do not use the roughly $120-$159/hour general repair figure; it would roughly double labor cost. Record the source and the fact that rates vary a lot by state.
  - Bands stay deliberately wide: low/mid/high must reflect hidden-damage and parts uncertainty.
  - When the table is built, give me the full list of `assumption` rows for review. I must be able to defend every row.
  - The "LLM free-guess" baseline is for comparison only and must never feed the table.
- Output the drivers of the estimate and the caveats (hidden damage risk, parts type, region).
- Also implement the "LLM free-guess cost" as a baseline field for comparison in the eval. Keep it out of the main UI result, behind a flag.

**FR5 Routing recommendation.** One of: `fast_track_candidate`, `adjuster_review`, `request_more_photos`, `possible_total_loss`, with reasons. Rules must be explicit, readable, and unit-tested. Low confidence, wide cost range, high severity, or unassessable areas push toward a human.

**FR6 Human in the loop.** The adjuster can edit any extracted field and accept or reject the result. Every correction is appended to a log (original value, corrected value, timestamp, request id). This log is eval data.

**FR7 UI.** One page served by the same app. Upload or paste URL, show results with confidence indicators, the cost range, routing and reasons, the quality-gate failure state, latency and cost per request, and the edit/accept flow. Clean and credible; do not over-polish.

**FR8 Eval harness (code only).** `python eval.py` runs the pipeline over a labeled set and prints a results table:
- make / model / color accuracy
- damage-item precision and recall by panel
- severity agreement (weighted kappa)
- cost-range coverage and error vs the reference
- abstention rate and routing distribution
- latency p50/p95 and dollars per claim
- model comparison (a larger and a smaller model) with the quality vs cost tradeoff

The labeled set must use real public images with real labels (check and record dataset licenses). Never fabricate labels. If the set is small, say so in the output header. If the network blocks a download, ask me to supply the images.

**License warning:** do not assume a dataset is usable. CarDD, for example, requires prior consent from its owners, defines commercial use to include testing commercial systems, forbids passing the data to third parties, and its images carry their own source copyrights. Do not download, use, or commit CarDD (or any similarly restricted dataset) unless I confirm I have permission. Present me with dataset options and their license terms first, and let me choose. Never commit dataset images to the repo; the eval script should read them from a local path.

## 4. Non-functional requirements

**Performance**
- Report p50/p95 latency per request. Targets to aim for (assumptions to validate, not promises): single image p95 < 15 s end to end.
- Resize/compress images before sending to the model (cap longest side) to control latency and token cost.

**Cost control**
- Track token usage and dollars per request and per claim; show them in the response and logs.
- Image-hash cache so identical images are not reprocessed.
- A configurable daily spend cap that fails closed with a clear message.

**Reliability**
- Timeouts on every external call, bounded retries with backoff, and a validation-retry for malformed model output (max 2).
- Graceful degradation: if the model is down, return a clear error and route to `adjuster_review`, never a fabricated result.
- Idempotent endpoint behavior; a stable request id on every response.

**Security**
- No secrets in the repo; `.env.example` only.
- **SSRF protection on URL input:** allow only http/https, resolve and block private, loopback and link-local ranges, cap redirects, enforce size and content-type limits, set a fetch timeout.
- Validate files by magic bytes, not just extension; cap file size and image dimensions (decompression bomb guard).
- Treat text inside images as untrusted data. Prompt-injection text in a photo must never change behavior; test with at least one such image.
- Rate limit per IP.

**Privacy**
- Do not persist uploaded images by default (process in memory). Logs must not contain image bytes or full URLs with tokens.
- License plates and faces may appear in photos: flag it in the response, do not store, and note the handling in HANDOFF.md. Redaction is out of scope unless trivial.

**Auditability and explainability**
- Every response records: request id, model id, prompt version, schema version, cost table version, input hash, timestamp.
- Every routing decision lists its reasons in plain English.

**Determinism**
- Temperature 0 where supported; pin model identifiers and prompt versions in config.

**Observability**
- Structured JSON logs with request id; a `/health` endpoint; a simple `/metrics`-style summary (counts by routing outcome, failure reasons, latency).

**Scalability (design for it, don't build it)**
- Keep the service stateless so it scales horizontally. Note in HANDOFF.md where a queue, worker pool, rate-limit budget with the model provider, and a real datastore would go. Do not build them.

**Maintainability and portability**
- Typed Python with Pydantic models at every boundary; small modules; unit tests for the cost engine, routing rules, quality-gate parsing, and SSRF guard.
- Runs locally with one documented command; a Dockerfile; deployed on **Railway**.

**Usability**
- Clear error and empty states; keyboard-usable form; readable on a laptop projector.

## 5. Architecture decisions I have made (challenge them before building if you disagree)

I made these deliberately: the brief is loosely defined on purpose, and the direction I take is part of what I'm assessed on. My reasoning: a single photo can't support a trustworthy repair price (hidden damage, regional parts and labor, OEM vs aftermarket), so the product is triage with calibrated uncertainty, not a price oracle.

1. FastAPI + Pydantic backend; frontend served by the same app (no separate frontend build unless you justify it).
2. Claude vision model for extraction with JSON-schema/tool-use structured output.
3. Hybrid cost engine (Section 3, FR4).
4. SQLite or flat files for the corrections log and request audit log only.
5. No fine-tuning, no auth, no production database, no real estimating-system integration, no fraud detection beyond the quality gate. These are intentional and will be stated as out of scope.

## 6. How I want you to work

1. **Plan before code.** Before writing any code, give me your proposed file structure and build order. Flag anything in this brief you think is wrong, underspecified, or would cut differently. Tell me before you build the version you disagree with.
2. **One vertical slice at a time, in order** (Section 7). After each, show me **real output**: actual extraction JSON from a real image, an actual cost range, an actual eval table, an actual response from the deployed URL. "It's done" without evidence isn't done.
3. **A phase is complete only when every "Done when" item is demonstrably true.** Report each item as pass/fail with evidence.
4. **Commit at each verified checkpoint.** At minimum one commit per phase.
5. **Document every architectural decision in commit messages:** what, why, and the alternative you rejected.
6. **Never fabricate data when real data is available.** Real images, real labels. Mark every assumption (cost table, labor rates, volume figures) as an assumption in code and output.
7. **Prefer simple solutions over reusable abstractions.** No frameworks-in-waiting, no config layers nobody needs.
8. **If a real constraint forces a scope cut** (API cost, rate limits, dataset access, runtime), tell me the tradeoff and your recommendation instead of silently picking one.
9. **Say what you don't know.** When unsure (a dataset license, a cost band, a regulatory point), say so and state how we would find out.
10. **Keep a running failure log.** Every real failure found while building (wrong make, missed damage, hallucinated panel, bad range, gate false positive) goes in `docs/failures.md` with the input, expected, and actual. I will use these in the demo.
11. **Run it, don't just write it.** Execute the code and tests yourself and show output. Never claim something works without running it.
12. **I must be able to defend every file.** After each phase, give me a 3-5 line plain-English summary of what was built and the tradeoff accepted.
13. **Keep updates tight.** Evidence and decisions, not recaps of steps I can see in the diff.
14. **Do not write the README, the evaluation write-up, or the deck.** Put facts in `docs/HANDOFF.md` instead.

## 7. Phases and "Done when" checklists

No time estimates. Move on only when the done-when list is true.

### Phase 0: Plan and scaffold
- File structure, build order, and your pushback on this brief presented and approved by me.
- Repo initialized with `.gitignore`, `.env.example`, dependency file, Dockerfile skeleton.
- `/health` returns 200 locally.
- **Done when:** I approve the plan, the app starts with one command, first commit exists.

### Phase 1: Extraction pipeline (FR1-FR3)
- Schema defined; upload and URL intake with validation and SSRF guard; quality gate; model call with structured output, validation, bounded retry; model/prompt/schema versions recorded; latency and token cost recorded.
- **Done when:** run on at least 8 real images (clean, hard/ambiguous, multi-damage, night/blurry, non-car, an image with injected text instructions, a screenshot/stock-looking image, multi-photo claim). I have seen the actual JSON for each. Non-car and injection cases are refused or ignored with a reason. A malformed-output retry is demonstrated. SSRF tests pass (private IPs, localhost, redirect to internal address blocked).

### Phase 2: Cost engine and routing (FR4-FR5)
- Deterministic cost table built to the FR4 table spec (versioned file, `source` and `confidence` on every row, body-shop labor rate default, wide bands), regional labor rate config, range output with drivers and caveats; routing rules; LLM-only cost baseline behind a flag.
- **Done when:** I have reviewed the full list of `assumption` rows and approved or changed them; the same real images show a cost range and routing decision; at least one low-confidence case shows `request_more_photos`; one severe case shows `adjuster_review` or `possible_total_loss`; unit tests for the table and routing pass; the table is labeled as an assumption in the API response.

### Phase 3: UI and human in the loop (FR6-FR7)
- One-page UI covering upload, URL, multi-photo, results with confidence, gate-failure state, cost and latency display, edit and accept flow, corrections log.
- **Done when:** I can run these four cases end to end in the browser: clean easy case, hard low-confidence case, non-car/injection refusal, adjuster correction that appears in the log.

### Phase 4: Eval harness (FR8)
- Dataset options and their license terms presented to me, and my choice confirmed, before any download (see the FR8 license warning).
- Labeled set from real public data (license noted), `eval.py`, results table, two-model comparison with quality vs cost per claim, cost-at-volume line labeled as an assumption.
- **Done when:** I have seen a real run's full table; n and label provenance are printed in the header; the larger vs smaller model comparison is shown; results are saved to `eval/results/` with the commit hash.

### Phase 5: Hardening and deploy (NFRs)
- Timeouts, rate limit, spend cap, structured logs, metrics summary, caching, no image persistence verified, tests green, Dockerfile builds.
- **Done when:** the public Railway URL accepts an upload and a URL and returns results; I have seen a successful live request and a live gate refusal; rate limit and spend cap are demonstrated; `/health` passes; no secrets exist in the repo or git history.

### Phase 6: Handoff
- Produce `docs/HANDOFF.md` and `docs/failures.md` (Section 9).
- **Done when:** a clean clone runs from the commands in HANDOFF.md, and every number in the handoff traces to a real run.

## 8. Success criteria

**Must have**
- Live Railway URL where an image (upload or URL) returns vehicle metadata, damage summary, and a cost range.
- Repo that runs from a clean clone with one documented command.
- Working eval harness with real numbers from a real run.
- Quality gate, routing, and human-correction log all working.

**What makes it significantly better than a "good" build**
- Cost is a range from a deterministic engine, not an LLM point guess, with the baseline for comparison.
- The system refuses and says "send another photo" instead of guessing.
- Injection, SSRF, and bad-input cases are tested, not just claimed.
- Every response is auditable (versions, hash, reasons).
- Cost and latency per claim are visible and measured.
- At least three real, documented failure modes I can show on purpose.

**Quality bars**
- No fabricated data presented as real. Every assumption labeled.
- I can explain every file in 30 seconds.

## 9. Handoff you must produce (raw material for my README, eval write-up, and deck)

`docs/HANDOFF.md`, facts only, no marketing:
- Exact setup and run commands (local and Docker) and the Railway deploy steps used.
- Data flow as numbered steps, and the file/module for each.
- Every decision made, with the tradeoff and alternative rejected.
- Real measured numbers: latency p50/p95, cost per claim, per model, from the eval run, with n and dataset provenance.
- Every assumption (cost table, labor rate, thresholds, targets) listed in one place.
- What is stubbed or intentionally not built, and where production would differ (queue, datastore, estimating-system integration, PII redaction, drift monitoring, model-provider rate limits).
- Known limitations and unanswered questions I should say "I don't know, here's how I'd find out" about.
- Suggested demo cases: which images show a win, a hard case, a refusal, and a deliberate failure, with the request outputs.

`docs/failures.md`: the running failure log from rule 10.
