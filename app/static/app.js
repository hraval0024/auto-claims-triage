// One-page UI. All server/model text is inserted with textContent (via el()), never innerHTML,
// so text read from a photo can't inject markup.
"use strict";

let VOCAB = null;
let CURRENT = null; // last ClaimResult

const $ = (id) => document.getElementById(id);
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
const conf = (c) => el("span", { class: `conf ${c}` }, `${c} confidence`);
const OUTCOME_TEXT = {
  fast_track_candidate: "Fast-track candidate",
  adjuster_review: "Adjuster review",
  request_more_photos: "Request more photos",
  possible_total_loss: "Possible total loss",
};
const FLAG_TEXT = {
  license_plate_visible: "License plate visible (not stored)",
  person_face_visible: "Person's face visible (not stored)",
  embedded_instruction_text: "Text in photo that looks like instructions: ignored",
  route_to_human: "Routed to a human",
};

function select(options, value, label) {
  const s = el("select", { "aria-label": label });
  for (const o of options) s.append(el("option", { value: o, selected: String(o) === String(value) }, o));
  return s;
}

// ---------- submit ----------
$("claim-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const fd = new FormData();
  for (const f of $("files").files) fd.append("files", f);
  for (const u of $("urls").value.split("\n").map((s) => s.trim()).filter(Boolean)) fd.append("urls", u);
  fd.append("region", $("region").value);
  if (![...fd.keys()].some((k) => k === "files" || k === "urls")) {
    $("form-status").textContent = "Add at least one photo or URL.";
    return;
  }
  $("submit-btn").disabled = true;
  $("form-status").textContent = "Assessing... (a single photo usually takes 5-15 s; several photos take longer)";
  try {
    const r = await fetch("/api/claims", { method: "POST", body: fd });
    const body = await r.json();
    if (!r.ok) {
      const msg = body.error || (body.detail && JSON.stringify(body.detail)) || `HTTP ${r.status}`;
      $("form-status").textContent = `Rejected: ${msg}`;
      $("result").hidden = true;
      return;
    }
    $("form-status").textContent = "";
    render(body);
  } catch (e) {
    $("form-status").textContent = `Request failed: ${e}`;
  } finally {
    $("submit-btn").disabled = false;
  }
});

// ---------- render ----------
function render(res) {
  CURRENT = res;
  $("result").hidden = false;
  $("review-status").textContent = "";
  $("boundary").textContent = res.boundary_notice;

  const bar = clear("summary-bar");
  const spend = (res.usage ? res.usage.cost_usd : 0) + (res.llm_baseline && res.llm_baseline.usage ? res.llm_baseline.usage.cost_usd : 0);
  bar.append(
    el("span", {}, "Status: ", el("strong", {}, res.status)),
    el("span", {}, "Latency: ", el("strong", {}, (res.latency_ms / 1000).toFixed(1) + " s")),
    el("span", {}, "Model cost for this request: ", el("strong", {}, "$" + spend.toFixed(4))),
    el("span", { class: "muted" }, "Request ", res.audit.request_id),
  );

  renderRouting(res.routing);

  const gate = clear("gate");
  if (res.status !== "ok") {
    const box = el("div", { class: "box warn" }, el("strong", {}, res.status === "error" ? "Automated assessment unavailable" : "These photos can't be assessed"));
    if (res.error) box.append(el("p", {}, res.error));
    if (res.gate.reasons.length) box.append(el("p", {}, "Why:"), el("ul", {}, res.gate.reasons.map((r) => el("li", {}, r))));
    if (res.gate.retake_advice.length) box.append(el("p", {}, "What to send instead:"), el("ul", {}, res.gate.retake_advice.map((r) => el("li", {}, r))));
    gate.append(box);
  } else if (res.gate.reasons.length) {
    gate.append(el("div", { class: "box" }, el("strong", {}, "Photo notes"), el("ul", {}, res.gate.reasons.map((r) => el("li", {}, r)))));
  }
  const warnings = res.prechecks.flatMap((p) => p.warnings);
  if (warnings.length) gate.append(el("p", { class: "muted" }, "Photo checks: " + warnings.join(" ")));

  const flags = clear("flags");
  if (res.flags.length) flags.append(el("div", {}, "Flags: ", res.flags.map((f) => el("span", { class: "chip" }, FLAG_TEXT[f] || f))));
  const conflicts = clear("conflicts");
  if (res.conflicts.length) conflicts.append(el("div", { class: "box bad" }, el("strong", {}, "Photos disagree"), el("ul", {}, res.conflicts.map((c) => el("li", {}, c)))));

  $("assessment").hidden = res.status !== "ok";
  if (res.status === "ok") {
    renderVehicle(res.vehicle);
    renderDamage(res.damage);
    $("summary-text").value = res.damage_summary || "";
    $("na-text").value = (res.not_assessable || []).join("\n");
  }
  renderCost(res.cost);
  renderBaseline(res.llm_baseline);

  const rr = clear("review-region");
  for (const r of VOCAB.regions) rr.append(el("option", { value: r, selected: res.cost && res.cost.region === r }, r));
  $("accept-btn").disabled = false;
  $("reject-btn").disabled = false;
  $("audit").textContent = JSON.stringify(res.audit, null, 2);
}

function renderRouting(routing) {
  const n = clear("routing");
  n.append(
    el("h3", {}, "Recommended next step: ", el("span", { class: `badge ${routing.outcome}` }, OUTCOME_TEXT[routing.outcome] || routing.outcome)),
    el("ul", {}, routing.reasons.map((r) => el("li", {}, r))),
    el("p", { class: "muted" }, `Rules ${routing.rules_version}. A recommendation, not a decision.`),
  );
}

function renderVehicle(v) {
  const t = clear("vehicle-table");
  t.append(el("tr", {}, el("th", {}, "Field"), el("th", {}, "Value (editable)"), el("th", {}, "Confidence")));
  for (const k of ["make", "model", "color"]) {
    t.append(el("tr", {}, el("td", {}, k), el("td", {}, el("input", { type: "text", id: `veh-${k}`, value: v[k].value, "aria-label": `vehicle ${k}` })), el("td", {}, conf(v[k].confidence))));
  }
  t.append(el("tr", {}, el("td", {}, "year range"),
    el("td", {},
      el("input", { type: "number", id: "veh-ys", value: v.year_range.start ?? "", "aria-label": "year from", style: "width:6em" }), " to ",
      el("input", { type: "number", id: "veh-ye", value: v.year_range.end ?? "", "aria-label": "year to", style: "width:6em" })),
    el("td", {}, conf(v.year_range.confidence))));
}

function damageRow(item, origIndex) {
  const tr = el("tr", { "data-orig": origIndex === null ? "" : String(origIndex) });
  const rm = el("input", { type: "checkbox", "aria-label": "remove this item", onchange: () => tr.classList.toggle("removed", rm.checked) });
  tr.append(
    el("td", {}, select(VOCAB.panels, item.panel, "panel")),
    el("td", {}, select(VOCAB.sides, item.side, "side")),
    el("td", {}, select(VOCAB.damage_types, item.damage_type, "damage type")),
    el("td", {}, select(VOCAB.severities, item.severity, "severity")),
    el("td", {}, item.confidence ? conf(item.confidence) : el("span", { class: "muted" }, "added by adjuster")),
    el("td", { class: "muted" }, item.photo_indices ? item.photo_indices.join(", ") : ""),
    el("td", { class: "muted" }, (item.cues || []).join(" | ")),
    el("td", {}, el("label", {}, rm, " remove")),
  );
  return tr;
}

function renderDamage(items) {
  const t = clear("damage-table");
  t.append(el("tr", {}, ["Panel", "Side (vehicle's own)", "Type", "Severity 1-4", "Confidence", "Photos", "Visible cues", ""].map((h) => el("th", {}, h))));
  if (!items.length) t.append(el("tr", {}, el("td", { colspan: 8, class: "muted" }, "No visible damage reported.")));
  items.forEach((it, i) => t.append(damageRow(it, i)));
}
$("add-item").addEventListener("click", () => {
  $("damage-table").append(damageRow({ panel: "other_unknown", side: "unknown", damage_type: "dent", severity: 1 }, null));
});

function renderCost(cost) {
  const n = clear("cost");
  const built = clear("cost-built");
  if (!cost) {
    n.append(el("p", { class: "muted" }, "No estimate: the photos could not be assessed."));
    $("cost-details").hidden = true;
    return;
  }
  $("cost-details").hidden = false;
  if (cost.status === "estimated") {
    // Range only. mid_usd stays in the API (routing/eval); it is deliberately not shown.
    n.append(el("div", { class: "cost-range" }, `${usd(cost.low_usd)} – ${usd(cost.high_usd)}`));
  } else if (cost.status === "no_damage") {
    n.append(el("div", { class: "cost-range" }, "No visible damage to price"));
  } else {
    n.append(el("div", { class: "cost-range" }, "Cost not estimable"),
      el("p", {}, `${usd(cost.partial_low_usd)} – ${usd(cost.partial_high_usd)} `, el("strong", {}, `(${cost.partial_label})`)),
      el("ul", {}, cost.not_estimable_reasons.map((r) => el("li", {}, r))));
  }
  n.append(el("p", { class: "muted" }, cost.assumption_notice));

  built.append(
    el("p", {}, `Table ${cost.cost_table_version} · region ${cost.region} · labor ${usd(cost.labor_rate_usd_per_hour)}/h · vehicle class ${cost.vehicle_class}` +
      (cost.hidden_damage_uplift_applied ? " · hidden-damage uplift applied to the high end" : "") +
      (cost.claim_minimum_applied ? " · $100 claim minimum applied" : "")),
    el("h4", {}, "Drivers"),
    el("ul", {}, cost.lines.map((l) => el("li", {}, l.low_usd === null ? l.driver : `${l.driver} → ${usd(l.low_usd)} – ${usd(l.high_usd)}`))),
    el("h4", {}, "Assumptions and caveats"),
    el("ul", {}, cost.caveats.map((c) => el("li", {}, c))),
  );
}

function renderBaseline(b) {
  const n = clear("baseline");
  if (!b) return; // hidden unless the server-side baseline flag is on
  const box = el("div", { class: "box" }, el("strong", {}, "LLM free-guess baseline (eval only)"), el("p", { class: "muted" }, b.notice));
  if (b.guess) box.append(el("p", {}, `${usd(b.guess.low_usd)} – ${usd(b.guess.high_usd)} (point ${usd(b.guess.point_usd)}): ${b.guess.rationale}`));
  else box.append(el("p", {}, `Baseline failed: ${b.error}`));
  n.append(box);
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

async function sendReview(decision) {
  $("accept-btn").disabled = $("reject-btn").disabled = true;
  try {
    const r = await fetch(`/api/claims/${CURRENT.audit.request_id}/review`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(collectReview(decision)),
    });
    const body = await r.json();
    if (!r.ok) throw new Error(body.detail ? JSON.stringify(body.detail) : `HTTP ${r.status}`);
    $("review-status").textContent = `${decision === "accept" ? "Accepted" : "Rejected"}: ${body.corrections.length} correction(s) logged at ${body.logged_at}. ${body.note}`;
    renderRouting(body.routing);
    renderCost(body.cost);
    loadLog();
  } catch (e) {
    $("review-status").textContent = `Review failed: ${e.message}`;
    $("accept-btn").disabled = $("reject-btn").disabled = false;
  }
}
$("accept-btn").addEventListener("click", () => sendReview("accept"));
$("reject-btn").addEventListener("click", () => sendReview("reject"));

// ---------- corrections log ----------
async function loadLog() {
  const t = clear("log-table");
  t.append(el("tr", {}, ["Time (UTC)", "Request", "Field", "Original", "Corrected", "Decision"].map((h) => el("th", {}, h))));
  try {
    const { corrections } = await (await fetch("/api/corrections?limit=50")).json();
    if (!corrections.length) t.append(el("tr", {}, el("td", { colspan: 6, class: "muted" }, "No corrections yet.")));
    for (const c of corrections) {
      t.append(el("tr", {}, el("td", {}, c.created_at.replace("T", " ").slice(0, 19)), el("td", { class: "muted" }, c.request_id.slice(0, 8)),
        el("td", {}, c.field), el("td", {}, c.original ?? ""), el("td", {}, c.corrected ?? ""), el("td", {}, c.decision ?? "")));
    }
  } catch (e) {
    t.append(el("tr", {}, el("td", { colspan: 6 }, `Could not load the log: ${e}`)));
  }
}
$("refresh-log").addEventListener("click", loadLog);

(async function init() {
  VOCAB = await (await fetch("/api/vocab")).json();
  loadLog();
})();
