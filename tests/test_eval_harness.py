"""eval.py self-test: normalization rules, kappa, and perfect predictions -> perfect scores (no API)."""

import json

import eval as ev


def test_normalization_rules():
    assert ev.make_match("mercedes-benz", "Mercedes") and ev.make_match("VW", "Volkswagen") and not ev.make_match("Ford", "Honda")
    assert ev.model_match("c-class", "C-Class (W203)") and ev.model_match("cutlass ciera", "Ciera") and not ev.model_match("sunny", "Bluebird")
    assert not ev.model_match("unknown", "") and ev.is_unknown("Unknown")
    assert ev.color_match("silver", "grey") and ev.color_match("blue and white", "white") and not ev.color_match("red", "blue")


def test_quadratic_kappa():
    assert ev.quadratic_kappa([(1, 1), (2, 2), (3, 3), (4, 4)]) == 1.0
    assert ev.quadratic_kappa([(1, 4), (4, 1), (2, 3), (3, 2)]) < 0


def test_perfect_predictions_score_perfectly(tmp_path):
    imgs, dmg, manifest = ev.load_labels()
    recs = []
    for i, r in imgs.items():
        ok = r["should_pass_gate"] == "yes"
        damage = [{"panel": d["panel"], "side": d["side"], "damage_type": d["damage_type"], "severity": int(d["severity"])} for d in dmg[i]]
        res = {"status": "ok" if ok else "gate_failed", "gate": {"codes": [] if ok else [r["gate_reason"]]},
               "vehicle": {**{k: {"value": r[k] or "unknown"} for k in ("make", "model", "color")},
                           "year_range": {"start": int(r["year_start"]) if r["year_start"] else None,
                                          "end": int(r["year_end"]) if r["year_end"] else None}},
               "damage": damage if ok else [], "cost": {"status": "estimated", "low_usd": 100.0, "high_usd": 300.0},
               "routing": {"outcome": "adjuster_review", "notes": []}, "usage": {"cost_usd": 0.01}}
        recs.append({"model": "fake", "image_id": i, "run": 1, "kind": "main", "client_s": 1.0, "result": res,
                     "baseline": {"guess": {"low_usd": 100, "point_usd": 200, "high_usd": 300}, "cost_usd": 0.001, "latency_s": 0.5},
                     "call_cost_usd": 0.011})
    (tmp_path / "runs.jsonl").write_text("\n".join(json.dumps(x) for x in recs) + "\n")
    (tmp_path / "meta.json").write_text(json.dumps({"models": ["fake"]}))
    m = ev.metrics(tmp_path)["models"]["fake"]
    assert m["gate"]["agree"] == m["gate"]["denominator"] == 34
    for k in ("make", "model", "color"):
        assert m[k]["acc_pct"] == 100.0, k
    assert m["year"]["denominator"] == 0 or m["year"]["acc_pct"] == 100.0
    assert m["panel"]["precision_pct"] == m["panel"]["recall_pct"] == 100.0
    assert m["damage_type"]["precision_pct"] == m["damage_type"]["recall_pct"] == 100.0
    assert m["side"]["agree_pct"] == 100.0 and m["severity"]["exact_pct"] == 100.0 and m["severity"]["weighted_kappa"] == 1.0
    assert m["severe_recall"]["sev3"]["found_at_sev3plus_pct"] == 100.0 and m["severe_recall"]["sev4"]["found_at_sev4_pct"] == 100.0
    assert m["cost"]["baseline_point_outside_engine_range"]["count"] == 0


def test_unicode_folding_is_symmetric():
    assert ev.make_match("citroen", "Citroën") and ev.make_match("Citroën", "CITROEN")
    assert ev.model_match("Škoda Octavia", "skoda octavia") and ev.color_match("Grís gray", "silver")
    assert ev.HARNESS_VERSION == "eval_v2"


def test_year_overlap_rule():
    lab = {"year_start": "1986", "year_end": "1990"}
    assert ev.year_match(lab, {"year_range": {"start": 1990, "end": 1993}})
    assert not ev.year_match(lab, {"year_range": {"start": 1991, "end": 1993}})
    assert not ev.year_match(lab, {"year_range": {"start": None, "end": None}})
