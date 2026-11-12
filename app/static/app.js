// One-page UI. All server/model text is inserted with textContent (via el()), never innerHTML,
// so text read from a photo can't inject markup. Adjuster notes are rendered the same way.
"use strict";

let VOCAB = null;
let CURRENT = null; // last ClaimResult
let SNAPSHOT = null; // review payload as rendered, to count the adjuster's edits
let REVIEWED = false; // double-submit guard: one review per claim in this screen
let PHOTOS = []; // photos of the claim on screen: {kind: "file", url, name} | {kind: "url", text}
let SELECTED = 0;

const $ = (id) => document.getElementById(id);
// All API calls go through here: session cookie is sent automatically (same origin); a 401 means
// the session ended, so go back to the access-code page. The code itself never touches JS or a URL.
async function api(url, opts = {}) {
  const r = await fetch(url, { credentials: "same-origin", ...opts });
  if (r.status === 401) { window.location.assign("/login"); throw new Error("Session ended. Please enter the access code again."); }
  return r;
}
function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined) continue;
    n.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return n;
}
const usd = (x) => "$" + Math.round(x).toLocaleString("en-US");
const clear = (id) => { const n = $(id); n.replaceChildren(); return n; };
const conf = (c) => el("span", { class: `conf ${c}`, title: `Model confidence: ${c}` }, c);
const human = (s) => String(s).replace(/_/g, " ");
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
// Stored timestamps are UTC ISO; show them in the viewer's local time.
const localTime = (iso) => new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
const localDateTime = (iso) => new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
const OUTCOME_TEXT = {
  fast_track_candidate: "Fast-track candidate",
  adjuster_review: "Adjuster review",
  request_more_photos: "Request more photos",
  possible_total_loss: "Possible total loss",
};
const ROUTES = ["fast_track_candidate", "adjuster_review", "request_more_photos", "possible_total_loss"];
const FLAG_TEXT = {
  license_plate_visible: "License plate visible (not stored)",
  person_face_visible: "Person's face visible (not stored)",
  embedded_instruction_text: "Text in photo that looks like instructions: ignored",
  route_to_human: "Routed to a human",
};
const REGION_TEXT = { standard: "Standard", low_cost: "Low cost", high_cost: "High cost" };
const NOTES_MAX = 1000;

function select(options, value, label, textFn = human) {
  const s = el("select", { "aria-label": label });
  for (const o of options) s.append(el("option", { value: o, selected: String(o) === String(value) }, textFn(o)));
  return s;
}
function setStatus(id, text, kind = "") {
  const n = $(id);
  n.textContent = text;
  n.className = n.className.replace(/\b(ok|error)\b/g, "").trim() + (kind ? " " + kind : "");
}

// ---------- photo picker: thumbnails (local object URLs, never uploaded until submit) ----------
let thumbUrls = [];
function renderThumbs() {
  thumbUrls.forEach((u) => URL.revokeObjectURL(u));
  thumbUrls = [];
  const list = clear("thumbs");
  [...$("files").files].forEach((f, i) => {
    const u = URL.createObjectURL(f);
    thumbUrls.push(u);
    list.append(el("li", { title: f.name }, el("img", { src: u, alt: `Photo ${i + 1}: ${f.name}` }), el("span", { class: "idx" }, `Photo ${i + 1}`)));
  });
}
$("files").addEventListener("change", renderThumbs);
const dz = $("dropzone");
["dragenter", "dragover"].forEach((e) => dz.addEventListener(e, () => dz.classList.add("drag")));
["dragleave", "drop"].forEach((e) => dz.addEventListener(e, () => dz.classList.remove("drag")));

function setBusy(busy) {
  const b = $("submit-btn");
  b.disabled = busy;
  b.classList.toggle("busy", busy);
  b.querySelector(".btn-label").textContent = busy ? "Assessing…" : "Assess claim";
  $("loading").hidden = !busy;
  if (busy) $("result").hidden = true;
}

// ---------- submitted photos (result area). Same order as the server: files first, then URLs. ----------
function releasePhotos() {
  PHOTOS.forEach((p) => p.url && URL.revokeObjectURL(p.url));
  PHOTOS = [];
  SELECTED = 0;
}
function capturePhotos(files, urls) {
  releasePhotos();
  // Separate object URLs from the intake thumbnails, so changing the file input later can't
  // break the result preview. Nothing is uploaded or stored by this.
  for (const f of files) PHOTOS.push({ kind: "file", url: URL.createObjectURL(f), name: f.name });
  for (const u of urls) PHOTOS.push({ kind: "url", text: u });
}
function renderPhotos() {
  const main = clear("photo-main");
  const strip = clear("photo-strip");
  $("photos-card").hidden = PHOTOS.length === 0;
  if (!PHOTOS.length) return;
  const p = PHOTOS[SELECTED];
  if (p.kind === "file") {
    main.append(el("a", { href: p.url, target: "_blank", rel: "noopener", title: "Open full size in a new tab" },
      el("img", { src: p.url, alt: `Photo ${SELECTED + 1}: ${p.name}` })),
      el("p", { class: "photo-caption muted small" }, `Photo ${SELECTED + 1} · ${p.name} · click to open full size`));
  } else {
    // The CSP allows only 'self', data: and blob: images, so a pasted URL can't be shown here.
    main.append(el("div", { class: "photo-placeholder" },
      el("strong", {}, `Photo ${SELECTED + 1}: photo from URL (preview not available)`), el("span", { class: "url-text" }, p.text)));
  }
  if (PHOTOS.length > 1) {
    PHOTOS.forEach((q, i) => {
      const inner = q.kind === "file" ? el("img", { src: q.url, alt: "" }) : el("span", { class: "url-tile" }, "URL");
      strip.append(el("li", {}, el("button", {
        type: "button", class: i === SELECTED ? "selected" : null, "aria-pressed": String(i === SELECTED),
        "aria-label": `Show photo ${i + 1}`, onclick: () => selectPhoto(i),
      }, inner, el("span", { class: "idx" }, `Photo ${i + 1}`))));
    });
  }
}
function selectPhoto(i) {
  if (i < 0 || i >= PHOTOS.length) return;
  SELECTED = i;
  renderPhotos();
}

// ---------- submit ----------
$("claim-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const files = [...$("files").files];
  const urls = $("urls").value.split("\n").map((s) => s.trim()).filter(Boolean);
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  for (const u of urls) fd.append("urls", u);
  fd.append("region", $("region").value);
  if (!files.length && !urls.length) {
    setStatus("form-status", "Add at least one photo or URL.", "error");
    return;
  }
  setBusy(true);
  setStatus("form-status", "A single photo usually takes 5-15 s; several photos take longer.");
  const slow = setTimeout(() => { setStatus("form-status", "Still working: the model is slow right now. If it takes over a minute, the claim is routed to a human adjuster instead."); }, 20000);
  try {
    const r = await api("/api/claims", { method: "POST", body: fd });
    const body = await r.json();
    if (!r.ok) {
      const msg = body.error || `HTTP ${r.status}`;
      const label = r.status === 429 || r.status === 503 ? "Not run" : "Rejected";
      setStatus("form-status", `${label}: ${msg}`, "error");
      return;
    }
    setStatus("form-status", "");
    capturePhotos(files, urls);
    render(body);
  } catch (e) {
    setStatus("form-status", `Request failed: ${e.message || e}`, "error");
  } finally {
    clearTimeout(slow);
    setBusy(false);
  }
});

// ---------- render ----------
function metric(label, value, cls = "") {
  return el("span", { class: `metric ${cls}` }, label, el("strong", {}, value));
}

function render(res) {
  CURRENT = res;
  REVIEWED = false;
  $("result").hidden = false;
  $("result").classList.remove("reviewed");
  setStatus("review-status", "");
  $("boundary").textContent = res.boundary_notice;

  const bar = clear("summary-bar");
  const spend = (res.usage ? res.usage.cost_usd : 0) + (res.llm_baseline && res.llm_baseline.usage ? res.llm_baseline.usage.cost_usd : 0);
  bar.append(
    metric("Latency", (res.latency_ms / 1000).toFixed(1) + " s"),
    metric("Model cost", "$" + spend.toFixed(4) + (res.usage && res.usage.cached ? " · cached" : "")),
    metric("Model", res.audit.model_id, "mono"),
    metric("Request", res.audit.request_id.slice(0, 8), "mono"),
  );
  if (res.usage && res.usage.cached) bar.lastChild.title = "Identical photos seen before: no model call";

  renderRouting(res.routing);
  renderOverride(null);

  const gate = clear("gate");
  if (res.status !== "ok") {
    const box = el("div", { class: "box warn", role: "alert" }, el("strong", {}, res.status === "error" ? "Automated assessment unavailable" : "These photos can't be assessed"));
    if (res.error) box.append(el("p", {}, res.error));
    if (res.gate.reasons.length) box.append(el("p", { class: "box-label" }, "Why"), el("ul", {}, res.gate.reasons.map((r) => el("li", {}, r))));
    if (res.gate.retake_advice.length) box.append(el("p", { class: "box-label" }, "What to send instead"), el("ul", {}, res.gate.retake_advice.map((r) => el("li", {}, r))));
    gate.append(box);
  } else if (res.gate.reasons.length) {
    gate.append(el("div", { class: "box info" }, el("strong", {}, "Photo notes"), el("ul", {}, res.gate.reasons.map((r) => el("li", {}, r)))));
  }
  const warnings = res.prechecks.flatMap((p) => p.warnings);
  if (warnings.length) gate.append(el("p", { class: "muted prechecks" }, "Photo checks: " + warnings.join(" ")));

  const flags = clear("flags");
  if (res.flags.length) flags.append(el("div", { class: "flagrow" }, el("span", { class: "small muted" }, "Flags"), res.flags.map((f) => el("span", { class: "chip" }, FLAG_TEXT[f] || human(f)))));
  const conflicts = clear("conflicts");
  if (res.conflicts.length) conflicts.append(el("div", { class: "box bad" }, el("strong", {}, "Photos disagree"), el("ul", {}, res.conflicts.map((c) => el("li", {}, c)))));

  const ok = res.status === "ok";
  $("vehicle-card").hidden = !ok;
  // Photos stay visible on a refusal too: the adjuster sees what was refused.
  $("assessment").hidden = false;
  $("assessment").classList.toggle("no-findings", !ok);
  if (ok) {
    renderVehicle(res.vehicle);
    renderDamage(res.damage);
    $("summary-text").value = res.damage_summary || "";
    $("na-text").value = (res.not_assessable || []).join("\n");
  }
  renderPhotos();
  renderCost(res.cost);
  renderBaseline(res.llm_baseline);

  const rr = clear("review-region");
  for (const r of VOCAB.regions) rr.append(el("option", { value: r, selected: res.cost ? res.cost.region === r : r === "standard" }, REGION_TEXT[r] || human(r)));
  const fr = clear("final-route");
  for (const o of ROUTES) {
    const sys = o === res.routing.outcome;
    fr.append(el("option", { value: o, selected: sys }, OUTCOME_TEXT[o] + (sys ? " (system recommendation)" : "")));
  }
  $("review-notes").value = "";
  initRange(res);
  $("adjuster-estimate").hidden = true;
  setReadOnly(false);
  $("review-form").hidden = false;
  $("review-card").hidden = false;
  $("readonly-banner").hidden = true;
  $("reviewed-card").hidden = true; // a new result replaces the completion card
  LAST_REVIEW = null;
  $("accept-btn").disabled = false;
  $("reject-btn").disabled = false;
  SNAPSHOT = formState();
  updateReviewUI();
  renderAudit(res.audit);
  $("result").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderRouting(routing) {
  const n = clear("routing");
  n.className = `card decision ${routing.outcome}`;
  // Filter: DOM append(null) would insert the text "null".
  n.append(...[
    el("div", { class: "decision-top" },
      el("div", {},
        el("div", { class: "eyebrow" }, "Recommended next step"),
        el("h3", {}, el("span", { class: `badge ${routing.outcome}` }, OUTCOME_TEXT[routing.outcome] || routing.outcome)))),
    el("ul", { class: "reasons" }, routing.reasons.map((r) => el("li", {}, r))),
    (routing.notes || []).length ? el("div", { class: "box warn" }, el("strong", {}, "Also recommended"),
      el("ul", {}, routing.notes.map((x) => el("li", {}, x)))) : null,
    el("p", { class: "muted rules" }, `Rules ${routing.rules_version}. A recommendation, not a decision.`),
  ].filter(Boolean));
}

// Shown beside the recommendation after an accepted override. States what happened; never
// judges whether the override was right.
function renderOverride(rev) {
  const n = clear("override-panel");
  const on = !!(rev && rev.route_overridden);
  n.hidden = !on;
  $("decision-row").classList.toggle("has-override", on);
  if (!on) return;
  n.append(
    el("div", { class: "eyebrow" }, "Adjuster override"),
    el("h3", {}, "Final route: ", el("span", { class: `badge ${rev.final_route}` }, OUTCOME_TEXT[rev.final_route]), " (adjuster override)"),
    el("p", {}, "System recommended: ", el("strong", {}, OUTCOME_TEXT[rev.routing.outcome])),
    el("p", { class: "override-reason" }, el("span", { class: "muted" }, "Reason: "), rev.notes || ""),
  );
}

function renderVehicle(v) {
  const t = clear("vehicle-table");
  for (const k of ["make", "model", "color"]) {
    t.append(el("tr", {}, el("th", { scope: "row" }, k), el("td", {}, el("input", { type: "text", id: `veh-${k}`, value: v[k].value, "aria-label": `vehicle ${k}` })), el("td", {}, conf(v[k].confidence))));
  }
  t.append(el("tr", {}, el("th", { scope: "row" }, "Year range"),
    el("td", {}, el("div", { class: "years" },
      el("input", { type: "number", id: "veh-ys", value: v.year_range.start ?? "", "aria-label": "year from", placeholder: "from" }), "to",
      el("input", { type: "number", id: "veh-ye", value: v.year_range.end ?? "", "aria-label": "year to", placeholder: "to" }))),
    el("td", {}, conf(v.year_range.confidence))));
}

function sevBar(s) {
  return el("span", { class: "sev-bar", "data-s": String(s), "aria-hidden": "true" }, el("i"), el("i"), el("i"), el("i"));
}

// Photo references in the findings are 1-based to match the photo labels ("Photo 1").
function photoRefs(indices) {
  if (!indices || !indices.length) return "–";
  return indices.map((i) => PHOTOS[i]
    ? el("button", { type: "button", class: "photo-ref", "aria-label": `Show photo ${i + 1}`, onclick: () => selectPhoto(i) }, String(i + 1))
    : el("span", {}, String(i + 1)));
}

function damageRow(item, origIndex) {
  const tr = el("tr", { "data-orig": origIndex === null ? "" : String(origIndex) });
  const rm = el("input", { type: "checkbox", "aria-label": "remove this item", onchange: () => tr.classList.toggle("removed", rm.checked) });
  const sevSel = select(VOCAB.severities, item.severity, "severity", String);
  const bar = sevBar(item.severity);
  sevSel.addEventListener("change", () => bar.setAttribute("data-s", sevSel.value));
  tr.append(
    el("td", {}, select(VOCAB.panels, item.panel, "panel")),
    el("td", {}, select(VOCAB.sides, item.side, "side")),
    el("td", {}, select(VOCAB.damage_types, item.damage_type, "damage type")),
    el("td", {}, el("span", { class: "sev" }, sevSel, bar)),
    el("td", {}, item.confidence ? conf(item.confidence) : el("span", { class: "conf adjuster" }, "adjuster")),
    el("td", { class: "num photo-refs" }, photoRefs(item.photo_indices)),
    el("td", { class: "cues" }, (item.cues || []).join(" · ")),
    el("td", { class: "rm-cell" }, rm),
  );
  return tr;
}

function renderDamage(items) {
  const t = clear("damage-table");
  t.append(el("tr", {}, ["Panel", "Side", "Type", "Severity 1-4", "Confidence", "Photo", "Visible cues", "Remove"].map((h) => el("th", {}, h))));
  if (!items.length) t.append(el("tr", {}, el("td", { colspan: 8, class: "empty-row" }, "No visible damage reported.")));
  items.forEach((it, i) => t.append(damageRow(it, i)));
}
$("add-item").addEventListener("click", () => {
  const empty = $("damage-table").querySelector(".empty-row");
  if (empty) empty.parentElement.remove();
  $("damage-table").append(damageRow({ panel: "other_unknown", side: "unknown", damage_type: "dent", severity: 1 }, null));
  updateReviewUI();
});

function renderCost(cost) {
  const n = clear("cost");
  const built = clear("cost-built");
  if (!cost) {
    n.append(el("div", { class: "cost-range text" }, "No estimate"), el("p", { class: "cost-sub" }, "The photos could not be assessed."));
    $("cost-details").hidden = true;
    return;
  }
  $("cost-details").hidden = false;
  if (cost.status === "estimated") {
    // Range only. mid_usd stays in the API (routing/eval); it is deliberately not shown.
    n.append(el("div", { class: "cost-range" }, `${usd(cost.low_usd)} – ${usd(cost.high_usd)}`),
      el("p", { class: "cost-sub" }, `Low to high range · ${(cost.high_usd / cost.low_usd).toFixed(1)}× spread reflects hidden-damage and parts uncertainty`));
  } else if (cost.status === "no_damage") {
    n.append(el("div", { class: "cost-range text" }, "No visible damage to price"));
  } else {
    n.append(el("div", { class: "cost-range text" }, "Cost not estimable"),
      el("p", { class: "cost-partial" }, `${usd(cost.partial_low_usd)} – ${usd(cost.partial_high_usd)} `, el("strong", {}, `(${cost.partial_label})`)),
      el("ul", {}, cost.not_estimable_reasons.map((r) => el("li", {}, r))));
  }
  n.append(el("p", { class: "assumption-note" }, cost.assumption_notice));

  const meta = [`Table ${cost.cost_table_version}`, `Region: ${REGION_TEXT[cost.region] || human(cost.region)}`,
    `Labor ${usd(cost.labor_rate_usd_per_hour)}/h`, `Vehicle class: ${human(cost.vehicle_class)}`];
  if (cost.hidden_damage_uplift_applied) meta.push("Hidden-damage uplift on high end");
  if (cost.claim_minimum_applied) meta.push("$100 claim minimum applied");
  built.append(
    el("div", { class: "meta-line" }, meta.map((m) => el("span", {}, m))),
    el("h4", {}, "Drivers"),
    el("ul", { class: "drivers" }, cost.lines.map((l) => el("li", {}, el("span", {}, l.driver),
      l.low_usd === null ? null : el("span", { class: "amt" }, `${usd(l.low_usd)} – ${usd(l.high_usd)}`)))),
    el("h4", {}, "Assumptions and caveats"),
    el("ul", {}, cost.caveats.map((c) => el("li", {}, c))),
  );
}

function renderBaseline(b) {
  const n = clear("baseline");
  if (!b) return; // hidden unless the server-side baseline flag is on
  const box = el("div", { class: "box" }, el("strong", {}, "LLM free-guess baseline (eval only)"), el("p", { class: "muted small" }, b.notice));
  if (b.guess) box.append(el("p", {}, `${usd(b.guess.low_usd)} – ${usd(b.guess.high_usd)} (point ${usd(b.guess.point_usd)}): ${b.guess.rationale}`));
  else box.append(el("p", {}, `Baseline failed: ${b.error}`));
  n.append(box);
}

function renderAudit(a) {
  const dl = clear("audit-kv");
  const rows = [["Request id", a.request_id], ["Timestamp", a.timestamp], ["Model", `${a.model_id} (effort ${a.model_effort})`],
    ["Prompt", a.prompt_version], ["Schema", a.schema_version], ["Cost table", a.cost_table_version],
    ["Input hashes", a.input_hashes.map((h) => h.slice(0, 16) + "…").join(", ")]];
  for (const [k, v] of rows) dl.append(el("dt", {}, k), el("dd", {}, v));
  $("audit").textContent = JSON.stringify(a, null, 2);
}

// ---------- review ----------
function collectReview(decision) {
  const body = { decision, region: $("review-region").value };
  if (CURRENT.status === "ok") {
    const num = (id) => ($(id).value === "" ? null : Number($(id).value));
    body.vehicle = { make: $("veh-make").value, model: $("veh-model").value, color: $("veh-color").value, year_start: num("veh-ys"), year_end: num("veh-ye") };
    body.damage = [...$("damage-table").querySelectorAll("tr[data-orig]")].map((tr) => {
      const [panel, side, type, sev] = [...tr.querySelectorAll("select")].map((s) => s.value);
      const orig = tr.getAttribute("data-orig");
      return { orig_index: orig === "" ? null : Number(orig), removed: tr.querySelector("input[type=checkbox]").checked,
               panel, side, damage_type: type, severity: Number(sev) };
    });
    body.damage_summary = $("summary-text").value;
    body.not_assessable = $("na-text").value.split("\n").map((s) => s.trim()).filter(Boolean);
  }
  return body;
}

// The editable findings as collectReview() sends them (decision, notes and final route excluded).
function formState() {
  const s = collectReview("accept");
  delete s.decision;
  return s;
}

// Count edits against the render-time snapshot, one per field, the way the server logs them
// (app/review.py diff): a removed item counts once, an added item counts once. The server's count
// is authoritative; this only drives the button label.
function countChanges(a, b) {
  let n = 0;
  if (a.vehicle && b.vehicle) for (const k of Object.keys(a.vehicle)) n += String(a.vehicle[k]) !== String(b.vehicle[k]);
  const orig = new Map((a.damage || []).map((d) => [d.orig_index, d]));
  for (const d of b.damage || []) {
    if (d.orig_index === null) { n += !d.removed; continue; }
    const o = orig.get(d.orig_index);
    if (d.removed) { n += 1; continue; }
    for (const k of ["panel", "side", "damage_type", "severity"]) n += String(o[k]) !== String(d[k]);
  }
  if (a.damage_summary !== undefined) n += a.damage_summary !== b.damage_summary;
  if (a.not_assessable) n += a.not_assessable.join("\n") !== b.not_assessable.join("\n");
  if (CURRENT.cost) n += a.region !== b.region; // the server ignores region when there is no estimate
  return n;
}

const isOverride = () => $("final-route").value !== CURRENT.routing.outcome;

function needsPersonWarning() {
  const sev4 = (CURRENT.damage || []).some((d) => d.severity === 4) ||
    (SNAPSHOT && (formState().damage || []).some((d) => !d.removed && d.severity === 4));
  return sev4 || CURRENT.flags.length > 0 || ["possible_total_loss", "adjuster_review"].includes(CURRENT.routing.outcome);
}

// ---------- adjuster-set final estimate (accept only; never re-routes, see app/review.py) ----------
let SYS_RANGE = null; // {low, high} in whole dollars when the system priced the claim, else null
let RANGE_TOUCHED = false; // only an edited range counts; untouched = send null so a re-priced range stands
const USD_MAX = 500000;
const fmtRange = (lo, hi) => (lo === null || lo === undefined ? "not estimated" : `${usd(lo)} – ${usd(hi)}`);
function parseUsd(text) {
  const t = text.replace(/[$,\s]/g, "");
  if (t === "") return null;
  return /^\d+$/.test(t) ? Number(t) : NaN;
}
function setRangeInputs(r) {
  $("range-low").value = r ? r.low.toLocaleString("en-US") : "";
  $("range-high").value = r ? r.high.toLocaleString("en-US") : "";
}
function setRangeError(msg) {
  $("range-error").textContent = msg;
  for (const id of ["range-low", "range-high"]) {
    $(id).classList.toggle("invalid", !!msg);
    $(id).setAttribute("aria-invalid", String(!!msg));
  }
}
function initRange(res) {
  const c = res.cost;
  SYS_RANGE = c && c.status === "estimated" ? { low: Math.round(c.low_usd), high: Math.round(c.high_usd) } : null;
  RANGE_TOUCHED = false;
  setRangeInputs(SYS_RANGE);
  setRangeError("");
  $("range-field").disabled = !c; // gate_failed / error: nothing to estimate
  $("range-help").textContent = !c ? "No estimate: the photos could not be assessed."
    : SYS_RANGE ? "Pre-filled with the system range. Change it to set your own estimate. Not a payout amount."
    : "The system could not price this claim. Enter your own range if you can. Not a payout amount.";
}
// changed = edited away from the pre-fill; error = why it can't be sent yet.
function rangeState() {
  if (!RANGE_TOUCHED || $("range-field").disabled) return { changed: false };
  const low = parseUsd($("range-low").value), high = parseUsd($("range-high").value);
  if (low === null && high === null) return { changed: false }; // both cleared: the system range (if any) stands
  if (SYS_RANGE && low === SYS_RANGE.low && high === SYS_RANGE.high) return { changed: false };
  let error = "";
  if (Number.isNaN(low) || Number.isNaN(high)) error = "Enter whole dollars, for example 1,250.";
  else if ((low === null) !== (high === null)) error = "Enter both a low and a high value.";
  else if (low > USD_MAX || high > USD_MAX) error = "Enter a value between $0 and $500,000.";
  else if (low > high) error = "Low must not be higher than High.";
  return { changed: true, low, high, error };
}
for (const id of ["range-low", "range-high"]) {
  $(id).addEventListener("input", () => {
    RANGE_TOUCHED = true;
    if ($("range-error").textContent) setRangeError(rangeState().error || "");
  });
  $(id).addEventListener("blur", () => { const v = parseUsd($(id).value); if (Number.isFinite(v)) $(id).value = v.toLocaleString("en-US"); });
}
$("range-reset").addEventListener("click", () => {
  setRangeInputs(SYS_RANGE);
  RANGE_TOUCHED = false;
  setRangeError("");
  updateReviewUI();
});

// "2 corrections, route override and range change"
function changePhrase(n, route, range) {
  const parts = [];
  if (n) parts.push(plural(n, "correction"));
  if (route) parts.push("route override");
  if (range) parts.push("range change");
  return parts.length < 2 ? parts[0] || "" : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

function updateReviewUI() {
  if (!CURRENT || REVIEWED || !SNAPSHOT) return;
  const n = countChanges(SNAPSHOT, formState());
  const ov = isOverride();
  const phrase = changePhrase(n, ov, rangeState().changed);
  $("accept-btn").textContent = phrase ? `Accept with ${phrase}` : "Accept as is";
  $("override-hint").hidden = !ov;
  $("fasttrack-warn").hidden = !(ov && $("final-route").value === "fast_track_candidate" && needsPersonWarning());
  $("notes-label").textContent = ov ? "Adjuster notes (required: reason for the override)" : "Adjuster notes (optional)";
  $("review-notes").required = ov;
  $("review-notes").setAttribute("aria-required", String(ov));
  if (!ov || $("review-notes").value.trim()) setNotesError("");
  updateNotesCount();
}
function updateNotesCount() {
  const left = NOTES_MAX - $("review-notes").value.length;
  $("notes-count").textContent = `${left} ${left === 1 ? "character" : "characters"} left`;
}
function setNotesError(msg) {
  $("notes-error").textContent = msg;
  $("review-notes").classList.toggle("invalid", !!msg);
  $("review-notes").setAttribute("aria-invalid", String(!!msg));
}
// Any edit in the result area (fields, rows, textareas, region, final route) updates the label live.
$("result").addEventListener("input", updateReviewUI);
$("result").addEventListener("change", updateReviewUI);

function setReadOnly(ro) {
  for (const n of document.querySelectorAll("#vehicle-table input, #damage-table select, #damage-table input, #summary-text, #na-text")) n.disabled = ro;
  $("add-item").hidden = ro;
}

async function sendReview(decision) {
  if (REVIEWED) return; // double-submit guard
  const notes = $("review-notes").value.trim();
  // Override applies to Accept only: a reject never sends final_route (the server also refuses it).
  const override = decision === "accept" && isOverride();
  // The adjuster's range also applies to Accept only: a reject never sends it (the server refuses it too).
  const range = decision === "accept" ? rangeState() : { changed: false };
  const notesMissing = override && !notes;
  if (notesMissing) setNotesError("Add a reason: overriding the system recommendation needs one.");
  if (range.changed && range.error) setRangeError(range.error);
  if (range.changed && range.error) { $("range-low").focus(); return; }
  if (notesMissing) { $("review-notes").focus(); return; }
  const body = { ...collectReview(decision), notes: notes || null };
  if (override) body.final_route = $("final-route").value;
  if (range.changed) { body.final_low_usd = range.low; body.final_high_usd = range.high; }
  $("accept-btn").disabled = $("reject-btn").disabled = true;
  try {
    const r = await api(`/api/claims/${CURRENT.audit.request_id}/review`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const res = await r.json();
    if (!r.ok) throw new Error(res.error || `HTTP ${r.status}`);
    REVIEWED = true;
    showReviewed(res);
    loadLog();
  } catch (e) {
    setStatus("review-status", `Review failed: ${e.message}`, "error");
    $("accept-btn").disabled = $("reject-btn").disabled = false;
  }
}
$("accept-btn").addEventListener("click", () => sendReview("accept"));
$("reject-btn").addEventListener("click", () => sendReview("reject"));
$("review-notes").addEventListener("input", updateNotesCount);

// ---------- review completion ----------
let LAST_REVIEW = null;

const fieldCorrections = (list) => list.filter((c) => !c.field.startsWith("estimate."));

function reviewLabel(res) {
  if (res.decision === "reject") return "Rejected";
  const phrase = changePhrase(fieldCorrections(res.corrections).length, res.route_overridden, res.estimate_overridden);
  return phrase ? `Accepted with ${phrase}` : "Accepted as is";
}

function estimateText(res) {
  if (res.estimate_overridden) return `Adjuster-set estimate: ${fmtRange(res.final_low_usd, res.final_high_usd)} (system: ${fmtRange(res.system_low_usd, res.system_high_usd)})`;
  if (res.final_low_usd !== null && res.final_low_usd !== undefined) return `System range: ${fmtRange(res.final_low_usd, res.final_high_usd)}`;
  return "Not estimated";
}

function clearIntake() {
  $("files").value = "";
  renderThumbs(); // revokes the intake thumbnails' object URLs only
  $("urls").value = "";
  $("region").value = "standard";
  setStatus("form-status", "");
}

function announce(text) {
  const n = $("announce");
  n.textContent = "";
  setTimeout(() => { n.textContent = text; }, 50); // re-announce even if the text is the same
}

// The whole result collapses into one "Claim reviewed" card. The result stays in the DOM, read-only,
// for "View reviewed claim"; the photo viewer's object URLs (PHOTOS) stay alive until the next claim.
function showReviewed(res) {
  LAST_REVIEW = res;
  renderRouting(res.routing);
  renderCost(res.cost);
  renderOverride(res);
  setReadOnly(true);
  $("result").classList.add("reviewed");
  $("review-card").hidden = true;
  $("readonly-banner").hidden = false;
  setStatus("review-status", "");

  $("reviewed-sub").textContent = `${reviewLabel(res)} · ${localTime(res.logged_at)} · claim ${res.request_id.slice(0, 8)}`;
  const route = clear("reviewed-route");
  route.append(el("span", { class: `badge small ${res.final_route}` }, OUTCOME_TEXT[res.final_route]));
  if (res.route_overridden) route.append(el("span", { class: "muted" }, ` Adjuster override. System recommended: ${OUTCOME_TEXT[res.routing.outcome]}`));
  $("reviewed-estimate").textContent = estimateText(res);
  $("adjuster-estimate").hidden = !res.estimate_overridden;
  $("adjuster-estimate").textContent = res.estimate_overridden ? estimateText(res) : "";
  const notes = $("reviewed-notes");
  notes.textContent = res.notes || "None";
  notes.classList.toggle("muted", !res.notes);

  setViewReviewed(false);
  $("reviewed-card").hidden = false;
  clearIntake();
  announce("Claim reviewed");
  window.scrollTo({ top: 0, behavior: "smooth" });
  $("next-claim-btn").focus({ preventScroll: true });
}

function setViewReviewed(open) {
  $("result").hidden = !open;
  const b = $("view-reviewed-btn");
  b.textContent = open ? "Hide reviewed claim" : "View reviewed claim";
  b.setAttribute("aria-expanded", String(open));
}
$("view-reviewed-btn").addEventListener("click", () => setViewReviewed($("result").hidden));

// ---------- next claim ----------
function startNextClaim() {
  clearIntake();
  releasePhotos(); // revokes the photo viewer's object URLs
  renderPhotos();
  $("review-notes").value = "";
  setNotesError("");
  setStatus("review-status", "");
  clear("final-route");
  SYS_RANGE = null;
  RANGE_TOUCHED = false;
  setRangeInputs(null);
  setRangeError("");
  renderOverride(null);
  $("reviewed-card").hidden = true;
  $("readonly-banner").hidden = true;
  $("review-card").hidden = false;
  setViewReviewed(false);
  $("result").classList.remove("reviewed");
  CURRENT = null;
  SNAPSHOT = null;
  REVIEWED = false;
  LAST_REVIEW = null;
  window.scrollTo({ top: 0, behavior: "smooth" });
  $("files").focus({ preventScroll: true }); // the file input sits inside the dropzone
  loadLog();
}
$("next-claim-btn").addEventListener("click", startNextClaim);

// ---------- review history ----------
const FIELD_TEXT = { make: "make", model: "model", color: "color", year_start: "year from", year_end: "year to",
  panel: "panel", side: "side", damage_type: "type", severity: "severity" };
const shown = (v) => (v === null || v === undefined || v === "" || v === "None" ? "(empty)" : v);

// One readable line per stored correction (field names as written by app/review.py diff).
function correctionLine(c) {
  const o = shown(c.original), n = shown(c.corrected);
  let m;
  if ((m = c.field.match(/^vehicle\.(\w+)$/))) return `Vehicle ${FIELD_TEXT[m[1]] || human(m[1])}: ${o} → ${n}`;
  if ((m = c.field.match(/^damage\[(\d+)\]\.(\w+)$/))) return `Damage ${Number(m[1]) + 1} ${FIELD_TEXT[m[2]] || human(m[2])}: ${human(o)} → ${human(n)}`;
  if ((m = c.field.match(/^damage\[(\d+)\]$/))) return `Damage ${Number(m[1]) + 1} removed: ${human(o)}`;
  if (c.field === "damage[+]") return `Damage added: ${human(n)}`;
  if (c.field === "damage_summary") return `Damage summary: "${o}" → "${n}"`;
  if (c.field === "not_assessable") return `Not visible / cannot assess: ${o} → ${n}`;
  if ((m = c.field.match(/^estimate\.(low|high)$/))) {
    const money = (v) => (/^\d+$/.test(String(v)) ? usd(Number(v)) : v);
    return `Estimate ${m[1]}: ${money(o)} → ${money(n)}`;
  }
  if (c.field === "cost.region") return `Re-price region: ${REGION_TEXT[c.original] || o} → ${REGION_TEXT[c.corrected] || n}`;
  return `${human(c.field)}: ${o} → ${n}`;
}

function routeCell(v) {
  // Rows from before route tracking have no route columns.
  if (v.route_overridden) return el("span", { class: "route-cell" }, `${OUTCOME_TEXT[v.system_route] || v.system_route} → ${OUTCOME_TEXT[v.final_route] || v.final_route} `, el("span", { class: "override-badge" }, "Override"));
  if (v.final_route) return OUTCOME_TEXT[v.final_route] || v.final_route;
  return el("span", { class: "muted" }, "–");
}

function historyRows(v) {
  const n = fieldCorrections(v.corrections).length; // the estimate rows are shown as "range change"
  const decision = (v.decision === "accept" ? "Accepted" : "Rejected") + (n ? `, ${plural(n, "correction")}` : "") +
    (v.estimate_overridden ? ", range change" : "");
  const expandable = v.corrections.length > 0 || !!v.notes || v.route_overridden;
  const detailId = `hist-detail-${v.id}`;
  const row = el("tr", { class: expandable ? "hist-row expandable" : "hist-row" });
  let btn = null;
  if (expandable) {
    btn = el("button", { type: "button", class: "chev", "aria-expanded": "false", "aria-controls": detailId,
      "aria-label": `Details for claim ${v.request_id.slice(0, 8)}` });
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const open = btn.getAttribute("aria-expanded") !== "true";
      btn.setAttribute("aria-expanded", String(open));
      $(detailId).hidden = !open;
    });
    row.addEventListener("click", () => btn.click()); // the whole row is a mouse target; the button is the keyboard one
  }
  row.append(el("td", { class: "num" }, localDateTime(v.created_at)), el("td", { class: "mono" }, v.request_id.slice(0, 8)),
    el("td", {}, decision), el("td", {}, routeCell(v)), el("td", { class: "chev-cell" }, btn));
  if (!expandable) return [row];
  const box = el("div", { class: "hist-detail-box" });
  if (v.corrections.length) box.append(el("p", { class: "box-label" }, "Corrections"), el("ul", {}, v.corrections.map((c) => el("li", {}, correctionLine(c)))));
  if (v.notes) box.append(el("p", { class: "box-label" }, "Notes"), el("p", { class: "hist-notes" }, v.notes));
  if (v.route_overridden) box.append(el("p", { class: "box-label" }, "System recommended"), el("p", {}, OUTCOME_TEXT[v.system_route] || v.system_route));
  const detail = el("tr", { id: detailId, class: "hist-detail", hidden: true }, el("td", { colspan: 5 }, box));
  return [row, detail];
}

async function loadLog() {
  const t = clear("history-table");
  t.append(el("thead", {}, el("tr", {}, ["Time", "Claim", "Decision", "Final route"].map((h) => el("th", { scope: "col" }, h)),
    el("th", { scope: "col" }, el("span", { class: "sr-only" }, "Details")))));
  const body = el("tbody");
  t.append(body);
  try {
    const { reviews } = await (await api("/api/reviews?limit=20")).json();
    if (!reviews.length) body.append(el("tr", {}, el("td", { colspan: 5, class: "empty-row" }, "No reviews yet.")));
    for (const v of reviews) body.append(...historyRows(v));
  } catch (e) {
    body.append(el("tr", {}, el("td", { colspan: 5, class: "empty-row" }, `Could not load the review history: ${e}`)));
  }
}
$("refresh-log").addEventListener("click", loadLog);

(async function init() {
  VOCAB = await (await api("/api/vocab")).json();
  loadLog();
})();
