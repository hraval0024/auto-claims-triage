"""Phase 4 evaluation harness.

Runs the SAME pipeline as the app (app.pipeline.run_claim) over the labeled eval set for several
models, plus the LLM free-guess baseline (app.llm.guess_cost, the function behind the app's
baseline flag) for the cost comparison, plus repeat runs on a fixed subset for repeatability.
Writes everything under eval/results/<commit>_<utc>/ and prints a results table.

Differences from the live app, on purpose: the image-hash cache is OFF (repeat runs must reach
the model) and the API's daily caps/rate limits are not involved (local run, nothing touches the
deployed ledger). The baseline is called separately so extraction latency is not inflated by it.

Labels: ChatGPT, model-generated, NOT human-verified -> every number is AGREEMENT with those
labels, not accuracy against adjusters.

Usage:
  uv run python eval.py                      # full run (refuses if the git tree has uncommitted changes)
  uv run python eval.py --report RESULTS_DIR # recompute metrics/report from saved runs
"""

import argparse
import csv
import json
import math
import re
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median

MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]
# Fixed BEFORE any eval result existed: every ~3rd id in sorted order (eval_007 was removed).
REPEAT_IDS = ["eval_002", "eval_005", "eval_008", "eval_011", "eval_014",
              "eval_017", "eval_021", "eval_024", "eval_028", "eval_032"]
REPEATS = 3  # total runs per subset image (run 1 = the main pass)
VOLUME_ASSUMPTION = 10_000  # claims/month, ASSUMPTION for the cost-at-volume line

ROOT = Path(__file__).resolve().parent
IMG_DIR = ROOT / "data" / "eval"


# ---------------------------------------------------------------- normalization (fixed up front)
MAKE_ALIASES = {"mercedes": "mercedesbenz", "benz": "mercedesbenz", "vw": "volkswagen", "chevy": "chevrolet",
                "landrover": "landrover", "alfa": "alfaromeo"}
COLOR_GROUPS = {"white": "white", "cream": "white", "ivory": "white", "black": "black",
                "silver": "gray", "gray": "gray", "grey": "gray", "charcoal": "gray", "gunmetal": "gray",
                "red": "red", "maroon": "red", "burgundy": "red", "crimson": "red",
                "blue": "blue", "navy": "blue", "teal": "blue", "green": "green", "yellow": "yellow", "gold": "yellow",
                "beige": "brown", "tan": "brown", "brown": "brown", "bronze": "brown", "champagne": "brown",
                "orange": "orange", "purple": "purple", "pink": "pink"}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def is_unknown(s: str) -> bool:
    return norm(s) in ("", "unknown", "na", "none")


def make_match(label: str, pred: str) -> bool:
    a, b = norm(label), norm(pred)
    return MAKE_ALIASES.get(a, a) == MAKE_ALIASES.get(b, b)


def model_match(label: str, pred: str) -> bool:
    """Loose on purpose: 'C-Class' matches 'C-Class (W203)', 'Ciera' matches 'Cutlass Ciera'."""
    a, b = norm(label), norm(pred)
    return bool(a) and bool(b) and (a in b or b in a)


def colors(s: str) -> set:
    return {COLOR_GROUPS[w] for w in re.findall(r"[a-z]+", (s or "").lower()) if w in COLOR_GROUPS}


def color_match(label: str, pred: str) -> bool:
    return bool(colors(label) & colors(pred))


def quadratic_kappa(pairs: list[tuple[int, int]], k: int = 4) -> float | None:
    if len(pairs) < 2:
        return None
    obs = [[0] * k for _ in range(k)]
    for a, b in pairs:
        obs[a - 1][b - 1] += 1
    n = len(pairs)
    ra = [sum(row) for row in obs]
    cb = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    w = [[(i - j) ** 2 / (k - 1) ** 2 for j in range(k)] for i in range(k)]
    num = sum(w[i][j] * obs[i][j] for i in range(k) for j in range(k))
    den = sum(w[i][j] * ra[i] * cb[j] / n for i in range(k) for j in range(k))
    return None if den == 0 else round(1 - num / den, 3)


# ---------------------------------------------------------------- data
def load_labels():
    imgs = {r["image_id"]: r for r in csv.DictReader(open(ROOT / "eval/labels/images_labels.csv"))}
    dmg = defaultdict(list)
    for r in csv.DictReader(open(ROOT / "eval/labels/damage_labels.csv")):
        dmg[r["image_id"]].append(r)
    manifest = {e["image_id"]: e for e in json.load(open(ROOT / "eval/manifest.json"))["images"]}
    return imgs, dmg, manifest


def per_panel(items: list[dict], key_panel="panel", key_side="side", key_sev="severity"):
    """panel -> {'sev': max severity, 'side': dominant side, 'types': set}"""
    out = {}
    by = defaultdict(list)
    for it in items:
        by[it[key_panel]].append(it)
    for p, its in by.items():
        sides = Counter(i[key_side] for i in its)
        out[p] = {"sev": max(int(i[key_sev]) for i in its), "side": sides.most_common(1)[0][0],
                  "types": {i["damage_type"] for i in its}}
    return out


# ---------------------------------------------------------------- running
class Budget:
    def __init__(self, cap: float, planned_calls: dict):
        self.cap, self.spent, self.lock, self.stop = cap, 0.0, threading.Lock(), False
        self.done = Counter()
        self.cost_by_model = defaultdict(list)
        self.planned = planned_calls

    def add(self, model: str, cost: float) -> None:
        with self.lock:
            self.spent += cost
            self.done[model] += 1
            self.cost_by_model[model].append(cost)
            projected = self.spent
            for m, n in self.planned.items():
                left = n - self.done[m]
                avg = mean(self.cost_by_model[m]) if self.cost_by_model[m] else 0.06  # unseen model: pessimistic
                projected += max(0, left) * avg
            self.projected = projected
            if projected > self.cap:
                self.stop = True


def git_commit() -> str:
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True).stdout.strip()
    if dirty:
        sys.exit(f"Refusing to run: uncommitted changes to tracked files (results must map to one commit):\n{dirty}")
    return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def run_model(model: str, ids: list[str], out_path: Path, budget: Budget, write_lock: threading.Lock, done: set) -> None:
    from app.intake import prepare_image
    from app.llm import LLMError, guess_cost
    from app.pipeline import run_claim

    plan = [(i, 1, "main") for i in ids] + [(i, r, "repeat") for r in range(2, REPEATS + 1) for i in REPEAT_IDS]
    for image_id, run, kind in plan:
        if budget.stop:
            return
        if (model, image_id, run) in done:
            continue
        data = (IMG_DIR / f"{image_id}.jpg").read_bytes()
        rec = {"model": model, "image_id": image_id, "run": run, "kind": kind}
        t = time.monotonic()
        try:
            res = run_claim([data], model_id=model, include_raw=True, include_llm_baseline=False, use_cache=False)
            rec["client_s"] = round(time.monotonic() - t, 2)
            rec["result"] = json.loads(res.model_dump_json())
            cost = res.usage.cost_usd if res.usage else 0.0
        except Exception as e:  # recorded, never retried to cherry-pick
            rec["client_s"] = round(time.monotonic() - t, 2)
            rec["exception"] = f"{type(e).__name__}: {e}"[:300]
            cost = 0.0
        if kind == "main" and rec.get("result", {}).get("status") == "ok":
            tb = time.monotonic()
            try:
                g, tally = guess_cost([prepare_image(data).jpeg_bytes], model_id=model)
                rec["baseline"] = {"guess": g.model_dump(), "cost_usd": round(tally.cost_usd, 5), "latency_s": round(time.monotonic() - tb, 2)}
                cost += tally.cost_usd
            except LLMError as e:
                rec["baseline"] = {"error": str(e), "cost_usd": round(e.usage.cost_usd, 5), "latency_s": round(time.monotonic() - tb, 2)}
                cost += e.usage.cost_usd
        rec["call_cost_usd"] = round(cost, 5)
        with write_lock:
            with out_path.open("a") as f:
                f.write(json.dumps(rec) + "\n")
        budget.add(model, cost)
        print(f"{model:18} {image_id} run{run} {rec.get('result', {}).get('status', rec.get('exception', '?'))[:40]:12} "
              f"{rec['client_s']:5.1f}s ${cost:.4f}  spent ${budget.spent:.2f} projected ${budget.projected:.2f}", flush=True)


def run_all(args) -> Path:
    commit = git_commit()
    from app.config import COST_TABLE_VERSION, PROMPT_VERSION, SCHEMA_VERSION, settings
    from app.routing import RULES_VERSION

    imgs, _, manifest = load_labels()
    ids = sorted(imgs)
    missing = [i for i in ids if not (IMG_DIR / f"{i}.jpg").exists()]
    if missing or set(ids) != set(manifest):
        sys.exit(f"Eval set mismatch: missing files {missing}; labels vs manifest equal: {set(ids) == set(manifest)}")
    out_dir = Path(args.resume) if args.resume else ROOT / "eval/results" / f"{commit[:7]}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {"commit": commit, "started": datetime.now(timezone.utc).isoformat(timespec="seconds"), "models": args.models,
            "effort": settings.model_effort, "prompt_version": PROMPT_VERSION, "schema_version": SCHEMA_VERSION,
            "rules_version": RULES_VERSION, "cost_table_version": COST_TABLE_VERSION, "prompt_cache": settings.prompt_cache,
            "image_hash_cache": "off", "n_images": len(ids), "repeat_ids": REPEAT_IDS, "repeats": REPEATS,
            "label_source": sorted({r["label_source"] for r in imgs.values()}), "max_spend_usd": args.max_spend}
    if not args.resume:
        (out_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    runs = out_dir / "runs.jsonl"
    done = set()
    if runs.exists():
        for line in runs.open():
            r = json.loads(line)
            done.add((r["model"], r["image_id"], r["run"]))
    planned = {m: len(ids) + (REPEATS - 1) * len(REPEAT_IDS) for m in args.models}
    # Pre-run projection from Phase 1-5 measurements (extraction + baseline on main pass; extraction only on repeats).
    est = {"claude-opus-5-5": (0.075, 0.06), "claude-sonnet-5-5": (0.03, 0.022), "claude-haiku-5-5": (0.004, 0.003)}
    projection = sum(len(ids) * est.get(m, (0.075, 0.06))[0] + (REPEATS - 1) * len(REPEAT_IDS) * est.get(m, (0.075, 0.06))[1]
                     for m in args.models)
    print(f"Projected spend before running: ${projection:.2f} (cap ${args.max_spend:.2f}); commit {commit[:7]}; results -> {out_dir}")
    if projection > args.max_spend:
        sys.exit("Projected spend exceeds the cap: not starting.")
    if args.resume and json.loads((out_dir / "meta.json").read_text()).get("commit") != commit:
        sys.exit("Resume refused: results dir was produced by a different commit.")
    budget = Budget(args.max_spend, planned)
    budget.projected = 0.0
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=len(args.models)) as ex:
        for fut in [ex.submit(run_model, m, ids, runs, budget, lock, done) for m in args.models]:
            fut.result()
    if budget.stop:
        print(f"\nSTOPPED: projected spend ${budget.projected:.2f} exceeds the ${args.max_spend:.2f} cap. Partial results in {out_dir}.")
        sys.exit(3)
    return out_dir


# ---------------------------------------------------------------- metrics
def pct(a, b):
    return None if not b else round(100 * a / b, 1)


def metrics(out_dir: Path) -> dict:
    imgs, dmg, manifest = load_labels()
    recs = [json.loads(line) for line in open(out_dir / "runs.jsonl")]
    meta = json.loads((out_dir / "meta.json").read_text())
    M = {}
    for model in meta["models"]:
        main = {r["image_id"]: r for r in recs if r["model"] == model and r["kind"] == "main"}
        res = {i: r.get("result") for i, r in main.items()}
        m = {"n_images_run": len(main), "exceptions": [i for i, r in main.items() if "exception" in r]}

        # gate: label should_pass vs did pass (status ok); denominator = all images run
        conf, wrong = Counter(), []
        for i, r in res.items():
            want = imgs[i]["should_pass_gate"] == "yes"
            got = (r or {}).get("status") == "ok"
            conf[(want, got)] += 1
            if want != got:
                wrong.append({"id": i, "label": "pass" if want else f"fail ({imgs[i]['gate_reason']})",
                              "model": (r or {}).get("status", "exception"), "model_codes": (r or {}).get("gate", {}).get("codes", [])})
        m["gate"] = {"denominator": len(res), "agree": conf[(True, True)] + conf[(False, False)],
                     "label_pass_model_pass": conf[(True, True)], "label_pass_model_fail": conf[(True, False)],
                     "label_fail_model_pass": conf[(False, True)], "label_fail_model_fail": conf[(False, False)], "disagreements": wrong}

        both = [i for i, r in res.items() if imgs[i]["should_pass_gate"] == "yes" and (r or {}).get("status") == "ok"]
        m["n_both_pass"] = len(both)

        # vehicle attributes: denominator = both-pass images whose label is not unknown
        for attr, fn in (("make", make_match), ("model", model_match), ("color", color_match)):
            den = [i for i in both if not is_unknown(imgs[i][attr])]
            correct = [i for i in den if fn(imgs[i][attr], res[i]["vehicle"][attr]["value"])]
            pred_unknown = [i for i in den if is_unknown(res[i]["vehicle"][attr]["value"])]
            m[attr] = {"denominator": len(den), "correct": len(correct), "acc_pct": pct(len(correct), len(den)),
                       "model_said_unknown": len(pred_unknown),
                       "misses": [{"id": i, "label": imgs[i][attr], "model": res[i]["vehicle"][attr]["value"]} for i in den if i not in correct]}

        # damage: per-image sets (micro), panel-level matching for side/severity
        tp_p = fp_p = fn_p = tp_t = fp_t = fn_t = 0
        side_pairs, sev_pairs, sev3, sev4, panel_misses, panel_extras = [], [], [0, 0, 0], [0, 0, 0], [], []
        false_damage = []
        for i in both:
            L = per_panel(dmg[i])
            P = per_panel([{"panel": d["panel"], "side": d["side"], "severity": d["severity"], "damage_type": d["damage_type"]}
                           for d in res[i]["damage"]])
            lp, pp = set(L), set(P)
            tp_p += len(lp & pp); fp_p += len(pp - lp); fn_p += len(lp - pp)
            if lp - pp:
                panel_misses.append({"id": i, "missed": sorted(lp - pp)})
            if pp - lp:
                panel_extras.append({"id": i, "extra": sorted(pp - lp)})
            lt = {t for v in L.values() for t in v["types"]}
            pt = {t for v in P.values() for t in v["types"]}
            tp_t += len(lt & pt); fp_t += len(pt - lt); fn_t += len(lt - pt)
            if imgs[i]["has_visible_damage"] == "no" and P:
                false_damage.append(i)
            for p in lp & pp:
                if L[p]["side"] in ("left", "right"):
                    side_pairs.append((i, p, L[p]["side"], P[p]["side"]))
                sev_pairs.append((L[p]["sev"], P[p]["sev"]))
            for p, v in L.items():
                bucket = sev3 if v["sev"] == 3 else sev4 if v["sev"] == 4 else None
                if bucket is not None:
                    bucket[0] += 1
                    if p in P:
                        bucket[1] += 1
                        bucket[2] += int(P[p]["sev"] >= v["sev"]) if v["sev"] == 4 else int(P[p]["sev"] >= 3)
        prec = lambda tp, fp: pct(tp, tp + fp)  # noqa: E731
        m["panel"] = {"denominator": f"{len(both)} both-pass images; {tp_p + fn_p} labeled panels, {tp_p + fp_p} predicted panels",
                      "precision_pct": prec(tp_p, fp_p), "recall_pct": pct(tp_p, tp_p + fn_p),
                      "misses": panel_misses, "extras": panel_extras}
        m["damage_type"] = {"denominator": f"per-image type sets over {len(both)} both-pass images ({tp_t + fn_t} labeled, {tp_t + fp_t} predicted)",
                            "precision_pct": prec(tp_t, fp_t), "recall_pct": pct(tp_t, tp_t + fn_t)}
        side_ok = [s for s in side_pairs if s[2] == s[3]]
        m["side"] = {"denominator": f"{len(side_pairs)} matched panels whose label side is left/right",
                     "agree_pct": pct(len(side_ok), len(side_pairs)),
                     "mirrored": [{"id": s[0], "panel": s[1], "label": s[2], "model": s[3]} for s in side_pairs
                                  if {s[2], s[3]} == {"left", "right"}]}
        m["severity"] = {"denominator": f"{len(sev_pairs)} matched panels (max severity per panel)",
                         "exact_pct": pct(sum(a == b for a, b in sev_pairs), len(sev_pairs)),
                         "within1_pct": pct(sum(abs(a - b) <= 1 for a, b in sev_pairs), len(sev_pairs)),
                         "weighted_kappa": quadratic_kappa(sev_pairs),
                         "model_higher": sum(b > a for a, b in sev_pairs), "model_lower": sum(b < a for a, b in sev_pairs)}
        m["severe_recall"] = {"sev3": {"labeled_panels": sev3[0], "panel_found_pct": pct(sev3[1], sev3[0]), "found_at_sev3plus_pct": pct(sev3[2], sev3[0])},
                              "sev4": {"labeled_panels": sev4[0], "panel_found_pct": pct(sev4[1], sev4[0]), "found_at_sev4_pct": pct(sev4[2], sev4[0])}}
        m["false_damage_on_undamaged"] = {"denominator": sum(1 for i in both if imgs[i]["has_visible_damage"] == "no"), "ids": false_damage}

        # cost engine vs free-guess baseline
        est = [res[i]["cost"] for i in both if res[i]["cost"] and res[i]["cost"]["status"] == "estimated"]
        ok_all = [i for i, r in res.items() if (r or {}).get("status") == "ok"]
        statuses = Counter(res[i]["cost"]["status"] for i in ok_all if res[i]["cost"])
        dis, comp = 0, 0
        refuse_vs_guess = []
        for i in ok_all:
            b = (main[i].get("baseline") or {}).get("guess")
            c = res[i]["cost"]
            if not b or not c:
                continue
            if c["status"] == "estimated":
                comp += 1
                dis += int(not (c["low_usd"] <= b["point_usd"] <= c["high_usd"]))
            elif c["status"] == "not_estimable":
                refuse_vs_guess.append(b["point_usd"])
        m["cost"] = {"accuracy": "N/A: no public ground truth",
                     "status_counts": dict(statuses),
                     "range_ratio_median": round(median([c["high_usd"] / c["low_usd"] for c in est]), 2) if est else None,
                     "range_width_usd_median": round(median([c["high_usd"] - c["low_usd"] for c in est])) if est else None,
                     "baseline_point_outside_engine_range": {"denominator": f"{comp} claims where the engine gave a full range", "count": dis, "pct": pct(dis, comp)},
                     "engine_not_estimable_but_baseline_guessed": {"count": len(refuse_vs_guess),
                                                                   "baseline_point_median_usd": round(median(refuse_vs_guess)) if refuse_vs_guess else None}}

        # routing / abstention
        outs = Counter((r or {}).get("routing", {}).get("outcome", "exception") for r in res.values())
        m["routing"] = {"denominator": len(res), "distribution": dict(outs),
                        "abstain_or_human_pct": pct(outs["request_more_photos"] + outs["adjuster_review"] + outs["possible_total_loss"], len(res)),
                        "request_more_photos_pct": pct(outs["request_more_photos"], len(res)),
                        "with_better_photos_note": sum(1 for r in res.values() if (r or {}).get("routing", {}).get("notes"))}

        # latency and cost (image-hash cache off: every call uncached)
        lat_main = sorted(r["client_s"] for r in main.values() if "result" in r)
        lat_all = sorted(r["client_s"] for r in recs if r["model"] == model and "result" in r)
        bl = [r["baseline"]["latency_s"] for r in main.values() if r.get("baseline")]
        m["latency_s"] = {"cache": "image-hash cache OFF: all calls uncached", "main_n": len(lat_main),
                          "main_p50": median(lat_main) if lat_main else None, "main_max": lat_main[-1] if lat_main else None,
                          "all_runs_n": len(lat_all), "all_runs_p50": median(lat_all) if lat_all else None,
                          "p95": "not reported: n < 100", "baseline_call_p50": median(bl) if bl else None}
        ext_costs = [r["result"]["usage"]["cost_usd"] for r in main.values() if r.get("result", {}).get("usage")]
        base_costs = [r["baseline"]["cost_usd"] for r in main.values() if r.get("baseline")]
        m["cost_per_claim_usd"] = {"extraction_mean": round(mean(ext_costs), 5) if ext_costs else None, "n": len(ext_costs),
                                   "baseline_call_mean": round(mean(base_costs), 5) if base_costs else None,
                                   "spend_this_model_total": round(sum(r["call_cost_usd"] for r in recs if r["model"] == model), 4),
                                   "at_volume_assumption": f"ASSUMPTION {VOLUME_ASSUMPTION:,} claims/month x extraction mean = "
                                                           f"${(mean(ext_costs) * VOLUME_ASSUMPTION if ext_costs else 0):,.0f}/month (excludes baseline, retries, infra)"}

        # repeatability on the fixed subset
        rep = defaultdict(list)
        for r in recs:
            if r["model"] == model and r["image_id"] in REPEAT_IDS and "result" in r:
                rep[r["image_id"]].append(r["result"])
        full = {i: rs for i, rs in rep.items() if len(rs) == REPEATS}

        def same(fn):
            return sum(1 for rs in full.values() if len({fn(x) for x in rs}) == 1)

        jac = []
        for rs in full.values():
            sets = [frozenset(d["panel"] for d in x["damage"]) for x in rs if x["status"] == "ok"]
            for a in range(len(sets)):
                for b in range(a + 1, len(sets)):
                    u = sets[a] | sets[b]
                    jac.append(1.0 if not u else len(sets[a] & sets[b]) / len(u))
        m["repeatability"] = {"denominator": f"{len(full)} subset images with all {REPEATS} runs",
                              "gate_same_pct": pct(same(lambda x: x["status"]), len(full)),
                              "routing_same_pct": pct(same(lambda x: x["routing"]["outcome"]), len(full)),
                              "make_same_pct": pct(same(lambda x: norm((x.get("vehicle") or {}).get("make", {}).get("value", "-"))), len(full)),
                              "max_severity_same_pct": pct(same(lambda x: max([d["severity"] for d in x["damage"]] or [0])), len(full)),
                              "cost_range_same_pct": pct(same(lambda x: json.dumps([(x.get("cost") or {}).get(k) for k in ("status", "low_usd", "high_usd")])), len(full)),
                              "panel_set_jaccard_mean": round(mean(jac), 3) if jac else None}
        M[model] = m
    return {"meta": meta, "models": M}


# ---------------------------------------------------------------- report
def report(out_dir: Path) -> str:
    R = metrics(out_dir)
    (out_dir / "summary.json").write_text(json.dumps(R, indent=2) + "\n")
    meta, M = R["meta"], R["models"]
    short = {m: m.replace("claude-", "").replace("-5-5", " 5.5") for m in M}
    rows = [
        ("Gate agreement (should-pass vs did-pass)", lambda m: f"{m['gate']['agree']}/{m['gate']['denominator']}"),
        ("Make accuracy", lambda m: f"{m['make']['acc_pct']}% ({m['make']['correct']}/{m['make']['denominator']})"),
        ("Model accuracy", lambda m: f"{m['model']['acc_pct']}% ({m['model']['correct']}/{m['model']['denominator']})"),
        ("Color accuracy", lambda m: f"{m['color']['acc_pct']}% ({m['color']['correct']}/{m['color']['denominator']})"),
        ("Panel precision / recall", lambda m: f"{m['panel']['precision_pct']}% / {m['panel']['recall_pct']}%"),
        ("Damage-type precision / recall", lambda m: f"{m['damage_type']['precision_pct']}% / {m['damage_type']['recall_pct']}%"),
        ("Side agreement (matched L/R panels)", lambda m: f"{m['side']['agree_pct']}% (n={m['side']['denominator'].split()[0]})"),
        ("Severity exact / within 1 / weighted kappa", lambda m: f"{m['severity']['exact_pct']}% / {m['severity']['within1_pct']}% / {m['severity']['weighted_kappa']}"),
        ("Sev-3 panels found / at sev 3+", lambda m: f"{m['severe_recall']['sev3']['panel_found_pct']}% / {m['severe_recall']['sev3']['found_at_sev3plus_pct']}% (n={m['severe_recall']['sev3']['labeled_panels']})"),
        ("Sev-4 panels found / at sev 4", lambda m: f"{m['severe_recall']['sev4']['panel_found_pct']}% / {m['severe_recall']['sev4']['found_at_sev4_pct']}% (n={m['severe_recall']['sev4']['labeled_panels']})"),
        ("Cost range high/low (median)", lambda m: f"{m['cost']['range_ratio_median']}x"),
        ("Baseline guess outside engine range", lambda m: f"{m['cost']['baseline_point_outside_engine_range']['pct']}% ({m['cost']['baseline_point_outside_engine_range']['count']}/{m['cost']['baseline_point_outside_engine_range']['denominator'].split()[0]})"),
        ("Routing: request_more_photos share", lambda m: f"{m['routing']['request_more_photos_pct']}%"),
        ("Latency p50 / max (s, uncached, n)", lambda m: f"{m['latency_s']['main_p50']} / {m['latency_s']['main_max']} (n={m['latency_s']['main_n']})"),
        ("Cost per claim (extraction mean)", lambda m: f"${m['cost_per_claim_usd']['extraction_mean']}"),
        ("Repeatability: routing / max sev same", lambda m: f"{m['repeatability']['routing_same_pct']}% / {m['repeatability']['max_severity_same_pct']}%"),
    ]
    lines = [f"# Eval results {out_dir.name}",
             f"Commit {meta['commit']} | {meta['n_images']} images (Wikimedia Commons, see eval/manifest.json; DEV images excluded) | "
             f"prompt {meta['prompt_version']} schema {meta['schema_version']} rules {meta['rules_version']} cost {meta['cost_table_version']} | effort {meta['effort']}",
             f"SMALL SET: n={meta['n_images']}. Labels: {meta['label_source']} -> AGREEMENT with one other model, NOT accuracy against adjusters.",
             "Cost accuracy: N/A: no public ground truth.", "",
             "| Metric | " + " | ".join(short.values()) + " |", "|---|" + "---|" * len(M)]
    for name, fn in rows:
        lines.append(f"| {name} | " + " | ".join(fn(M[m]) for m in M) + " |")
    text = "\n".join(lines) + "\n"
    (out_dir / "report.md").write_text(text)
    return text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=MODELS)
    ap.add_argument("--max-spend", type=float, default=15.0)
    ap.add_argument("--resume", help="results dir to continue (same commit only)")
    ap.add_argument("--report", help="recompute metrics/report for a results dir")
    args = ap.parse_args()
    out_dir = Path(args.report) if args.report else run_all(args)
    print(report(out_dir))
    print(f"Saved under {out_dir}")


if __name__ == "__main__":
    main()
