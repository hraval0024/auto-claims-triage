"""Adjuster review + corrections log, with the model stubbed (no API cost)."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import pipeline
from app.llm import UsageTally
from app.main import app
from app.schemas import ModelOutput
from tests.helpers import AUTH, model_output_dict, textured_jpeg

client = TestClient(app, headers=AUTH)


@pytest.fixture(autouse=True)
def stub_model(monkeypatch, tmp_db):
    damage = [
        {"photo_index": 0, "panel": "rear_bumper", "side": "left", "damage_type": "dent", "severity": 2, "confidence": "high", "cues": "a"},
        {"photo_index": 0, "panel": "taillamp", "side": "left", "damage_type": "crack", "severity": 3, "confidence": "medium", "cues": "b"},
    ]
    monkeypatch.setattr(pipeline, "call_model", lambda images, **kw: (
        ModelOutput.model_validate(model_output_dict(damage=damage)), UsageTally("claude-sonnet-5-5", 1000, 0, 0, 200, 1)))
    yield tmp_db


def new_claim() -> dict:
    r = client.post("/api/claims", files=[("files", ("a.jpg", textured_jpeg(), "image/jpeg"))])
    assert r.status_code == 200
    return r.json()


def items_as_sent(claim):
    return [{"orig_index": i, "removed": False, "panel": d["panel"], "side": d["side"],
             "damage_type": d["damage_type"], "severity": d["severity"]} for i, d in enumerate(claim["damage"])]


def vehicle_as_sent(claim):
    v = claim["vehicle"]
    return {"make": v["make"]["value"], "model": v["model"]["value"], "color": v["color"]["value"],
            "year_start": v["year_range"]["start"], "year_end": v["year_range"]["end"]}


def test_accept_without_changes_logs_review_but_no_corrections():
    c = new_claim()
    r = client.post(f"/api/claims/{c['audit']['request_id']}/review",
                    json={"decision": "accept", "vehicle": vehicle_as_sent(c), "damage": items_as_sent(c),
                          "damage_summary": c["damage_summary"], "not_assessable": c["not_assessable"], "region": "standard"})
    assert r.status_code == 200 and r.json()["corrections"] == []
    log = client.get("/api/corrections").json()
    assert log["reviews"][0]["decision"] == "accept" and log["reviews"][0]["n_corrections"] == 0


def test_corrections_are_logged_field_by_field_and_repriced():
    c = new_claim()
    rid = c["audit"]["request_id"]
    items = items_as_sent(c)
    taillamp = next(i for i in items if i["panel"] == "taillamp")
    taillamp["side"] = "right"  # side correction
    bumper = next(i for i in items if i["panel"] == "rear_bumper")
    bumper["severity"] = 1
    items.append({"orig_index": None, "removed": False, "panel": "trunk_tailgate", "side": "center", "damage_type": "scratch_scuff", "severity": 1})
    veh = vehicle_as_sent(c) | {"make": "Honda"}
    r = client.post(f"/api/claims/{rid}/review", json={"decision": "accept", "vehicle": veh, "damage": items})
    assert r.status_code == 200
    got = {(x["field"], x["original"], x["corrected"]) for x in r.json()["corrections"]}
    ti, bi = c["damage"].index(next(d for d in c["damage"] if d["panel"] == "taillamp")), c["damage"].index(next(d for d in c["damage"] if d["panel"] == "rear_bumper"))
    assert ("vehicle.make", "Toyota", "Honda") in got
    assert (f"damage[{ti}].side", "left", "right") in got
    assert (f"damage[{bi}].severity", "2", "1") in got
    assert ("damage[+]", "(none)", "center trunk_tailgate scratch_scuff severity 1") in got
    assert r.json()["cost"]["status"] == "estimated" and "adjuster" in r.json()["note"]
    rows = client.get("/api/corrections").json()["corrections"]
    assert {row["request_id"] for row in rows} == {rid} and len(rows) == 4
    assert all(row["created_at"] and row["decision"] == "accept" for row in rows)


def test_removed_item_is_logged_and_not_priced():
    c = new_claim()
    items = items_as_sent(c)
    for i in items:
        if i["panel"] == "taillamp":
            i["removed"] = True
    r = client.post(f"/api/claims/{c['audit']['request_id']}/review", json={"decision": "accept", "vehicle": vehicle_as_sent(c), "damage": items}).json()
    assert any(x["corrected"] == "(removed)" for x in r["corrections"])
    assert all(line["panel"] != "taillamp" for line in r["cost"]["lines"])


def test_originals_come_from_the_store_not_the_client():
    """A client cannot rewrite history: originals in the log are what the system returned."""
    c = new_claim()
    items = items_as_sent(c)
    r = client.post(f"/api/claims/{c['audit']['request_id']}/review", json={"decision": "accept", "vehicle": vehicle_as_sent(c) | {"make": "Toyota"}, "damage": items})
    assert r.json()["corrections"] == []  # same as stored -> nothing to log


def test_dropping_an_item_silently_is_rejected():
    c = new_claim()
    r = client.post(f"/api/claims/{c['audit']['request_id']}/review", json={"decision": "accept", "vehicle": vehicle_as_sent(c), "damage": items_as_sent(c)[:1]})
    assert r.status_code == 422 and "removed=true" in r.json()["error"]


def test_reject_logs_decision_without_repricing():
    c = new_claim()
    r = client.post(f"/api/claims/{c['audit']['request_id']}/review", json={"decision": "reject"}).json()
    assert r["decision"] == "reject" and r["cost"] == c["cost"]


def test_unknown_request_id_404():
    assert client.post("/api/claims/nope/review", json={"decision": "accept"}).status_code == 404


def test_region_change_is_logged_and_applied():
    c = new_claim()
    r = client.post(f"/api/claims/{c['audit']['request_id']}/review",
                    json={"decision": "accept", "vehicle": vehicle_as_sent(c), "damage": items_as_sent(c), "region": "high_cost"}).json()
    assert ("cost.region", "standard", "high_cost") in {(x["field"], x["original"], x["corrected"]) for x in r["corrections"]}
    assert r["cost"]["region"] == "high_cost"


def test_no_image_bytes_in_the_database(tmp_db):
    img = textured_jpeg()
    client.post("/api/claims", files=[("files", ("a.jpg", img, "image/jpeg"))])
    raw = tmp_db.read_bytes()
    assert img[:64] not in raw and b"\xff\xd8\xff" not in raw
    stored = sqlite3.connect(tmp_db).execute("SELECT result_json FROM requests").fetchone()[0]
    assert "raw_model_output\": null" in stored.replace(" ", "") or '"raw_model_output":null' in stored


def test_ui_page_and_vocab_served():
    assert "Claims Triage" in client.get("/").text
    v = client.get("/api/vocab").json()
    assert "fender" in v["panels"] and v["regions"] == ["low_cost", "standard", "high_cost"]
    js = client.get("/static/app.js").text
    assert ".innerHTML" not in js  # model text is always inserted as text
    assert "mid_usd" in js and "deliberately not shown" in js


# ---------- review UX: no-op accept, notes, route override, migration ----------
def review_post(c, **body):
    return client.post(f"/api/claims/{c['audit']['request_id']}/review", json=body)


def unedited(c, **extra):
    return {"decision": "accept", "vehicle": vehicle_as_sent(c), "damage": items_as_sent(c),
            "damage_summary": c["damage_summary"], "not_assessable": c["not_assessable"], "region": "standard", **extra}


def test_accept_as_is_keeps_stored_cost_and_routing():
    c = new_claim()
    r = review_post(c, **unedited(c)).json()
    assert r["corrections"] == [] and r["note"] == "Accepted as is. No changes were made."
    assert r["cost"] == c["cost"] and r["routing"] == c["routing"]
    assert r["system_route"] == r["final_route"] == c["routing"]["outcome"] and r["route_overridden"] is False


def test_accept_as_is_does_not_reroute_a_low_confidence_claim(monkeypatch):
    """The old code rebuilt items as adjuster-set (high confidence) on every accept, so an unedited
    accept could turn 'request more photos' into a different route."""
    damage = [{"photo_index": 0, "panel": "front_door", "side": "left", "damage_type": "dent",
               "severity": 2, "confidence": "low", "cues": "faint dent"}]
    monkeypatch.setattr(pipeline, "call_model", lambda images, **kw: (
        ModelOutput.model_validate(model_output_dict(damage=damage)), UsageTally("claude-sonnet-5-5", 1000, 0, 0, 200, 1)))
    c = new_claim()
    assert c["routing"]["outcome"] == "request_more_photos"
    r = review_post(c, **unedited(c)).json()
    assert r["routing"] == c["routing"] and r["final_route"] == "request_more_photos" and r["cost"] == c["cost"]
    # Contrast: the same claim with one real correction is re-routed with adjuster-set (high) confidence.
    items = items_as_sent(c)
    items[0]["severity"] = 1
    assert review_post(c, **unedited(c, damage=items)).json()["routing"]["outcome"] != "request_more_photos"


def test_correction_still_reprices_and_reroutes():
    c = new_claim()
    items = items_as_sent(c)
    next(i for i in items if i["panel"] == "taillamp")["severity"] = 4
    r = review_post(c, **unedited(c, damage=items)).json()
    assert len(r["corrections"]) == 1 and "Re-priced" in r["note"]
    assert r["cost"] != c["cost"] and r["cost"]["status"] == "not_estimable"
    assert r["routing"] != c["routing"] and any("Severity-4" in x for x in r["routing"]["reasons"])  # re-routed
    assert r["final_route"] == r["routing"]["outcome"]
    assert r["route_overridden"] is False


def test_notes_are_trimmed_stored_and_returned():
    c = new_claim()
    r = review_post(c, **unedited(c, notes="  checked against photo 1  ")).json()
    assert r["notes"] == "checked against photo 1"
    assert client.get("/api/corrections").json()["reviews"][0]["notes"] == "checked against photo 1"
    r2 = review_post(c, **unedited(c, notes="   ")).json()
    assert r2["notes"] is None


def test_notes_over_1000_chars_are_rejected():
    c = new_claim()
    assert review_post(c, **unedited(c, notes="x" * 1000)).status_code == 200
    r = review_post(c, **unedited(c, notes="x" * 1001))
    assert r.status_code == 422 and r.json()["fields"] == ["notes"]


def test_route_override_is_stored_and_does_not_change_cost():
    c = new_claim()
    assert c["routing"]["outcome"] != "possible_total_loss"
    r = review_post(c, **unedited(c, final_route="possible_total_loss", notes="Frame looks bent in photo 1")).json()
    assert r["route_overridden"] is True and r["final_route"] == "possible_total_loss"
    assert r["system_route"] == c["routing"]["outcome"]
    assert r["routing"] == c["routing"] and r["cost"] == c["cost"]  # recommendation and cost untouched
    row = client.get("/api/corrections").json()["reviews"][0]
    assert (row["system_route"], row["final_route"], row["route_overridden"], row["notes"]) == (
        c["routing"]["outcome"], "possible_total_loss", True, "Frame looks bent in photo 1")


def test_route_override_requires_notes():
    c = new_claim()
    for notes in (None, "", "   "):
        r = review_post(c, **unedited(c, final_route="possible_total_loss", notes=notes))
        assert r.status_code == 422 and "reason" in r.json()["error"]
    assert client.get("/api/corrections").json()["reviews"] == []  # refused requests are not logged


def test_selecting_the_system_route_is_not_an_override():
    c = new_claim()
    r = review_post(c, **unedited(c, final_route=c["routing"]["outcome"])).json()  # no notes needed
    assert r["route_overridden"] is False and r["final_route"] == c["routing"]["outcome"]


def test_route_override_with_reject_is_refused():
    c = new_claim()
    r = review_post(c, decision="reject", final_route="possible_total_loss", notes="x")
    assert r.status_code == 422 and "only allowed with accept" in r.json()["error"]


def test_override_with_correction_reprices_then_applies_final_route():
    c = new_claim()
    items = items_as_sent(c)
    next(i for i in items if i["panel"] == "taillamp")["severity"] = 4
    r = review_post(c, **unedited(c, damage=items, final_route="fast_track_candidate", notes="Adjuster judgment")).json()
    assert r["cost"]["status"] == "not_estimable"  # re-priced with the correction
    assert r["routing"]["outcome"] != "fast_track_candidate"  # the system's re-routed recommendation
    assert r["final_route"] == "fast_track_candidate" and r["route_overridden"] is True


def test_corrections_endpoint_returns_review_fields():
    c = new_claim()
    review_post(c, **unedited(c, notes="ok"))
    row = client.get("/api/corrections").json()["reviews"][0]
    assert {"notes", "system_route", "final_route", "route_overridden", "n_corrections", "decision"} <= row.keys()


def test_migration_adds_columns_to_old_schema_and_is_idempotent(tmp_db):
    from app import store
    old = sqlite3.connect(tmp_db)  # the reviews table as first deployed
    old.execute("CREATE TABLE reviews (id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL, "
                "decision TEXT NOT NULL, n_corrections INTEGER NOT NULL, created_at TEXT NOT NULL)")
    old.execute("INSERT INTO reviews (request_id, decision, n_corrections, created_at) VALUES ('old1', 'accept', 2, '2026-11-10T00:00:00+00:00')")
    old.commit()
    old.close()
    rows = store.recent_reviews()  # first connection runs the migration
    assert rows == [{"id": 1, "request_id": "old1", "decision": "accept", "n_corrections": 2,
                     "created_at": "2026-11-10T00:00:00+00:00", "notes": None, "system_route": None,
                     "final_route": None, "route_overridden": False, "system_low_usd": None, "system_high_usd": None,
                     "final_low_usd": None, "final_high_usd": None, "estimate_overridden": False}]
    conn = sqlite3.connect(tmp_db)
    assert store._migrate(conn) == []  # second run: nothing to add
    cols = [r[1] for r in conn.execute("PRAGMA table_info(reviews)")]
    assert cols[5:] == ["notes", "system_route", "final_route", "route_overridden", "system_low_usd",
                        "system_high_usd", "final_low_usd", "final_high_usd", "estimate_overridden"]
    conn.close()
    store.log_review("new1", "accept", [], notes="n", system_route="adjuster_review", final_route="adjuster_review")
    assert [r["request_id"] for r in store.recent_reviews()] == ["new1", "old1"]


def test_review_notes_never_reach_the_app_log(capsys):
    from app.logs import setup_logging
    setup_logging()
    c = new_claim()
    review_post(c, **unedited(c, final_route="possible_total_loss", notes="Owner Jane Q. Example, 555-0100"))
    out = capsys.readouterr().out
    assert "review" in out  # the request itself is logged...
    assert "Jane Q. Example" not in out and "555-0100" not in out  # ...its notes are not


# ---------- GET /api/reviews (review history) ----------
def test_reviews_endpoint_groups_corrections_under_the_right_review():
    c = new_claim()
    items = items_as_sent(c)
    items[0]["severity"] = 1
    review_post(c, **unedited(c, damage=items))  # review 1 of this request: 1 correction
    items2 = items_as_sent(c)
    items2[1]["side"] = "right"
    review_post(c, **unedited(c, damage=items2, vehicle=vehicle_as_sent(c) | {"model": "Camry"},
                              final_route="possible_total_loss", notes="  second look  "))  # review 2: 2 corrections
    c2 = new_claim()
    review_post(c2, decision="reject")  # another request, nothing to group
    rows = client.get("/api/reviews").json()["reviews"]
    assert [r["request_id"] for r in rows] == [c2["audit"]["request_id"], c["audit"]["request_id"], c["audit"]["request_id"]]
    newest, second, first = rows
    assert newest["corrections"] == [] and newest["decision"] == "reject"
    assert {x["field"] for x in second["corrections"]} == {"vehicle.model", "damage[1].side"} and second["n_corrections"] == 2
    assert first["corrections"] == [{"field": "damage[0].severity", "original": str(c["damage"][0]["severity"]), "corrected": "1"}]
    assert (second["notes"], second["system_route"], second["final_route"], second["route_overridden"]) == (
        "second look", c["routing"]["outcome"], "possible_total_loss", True)
    assert first["notes"] is None and first["route_overridden"] is False
    assert set(newest) == {"id", "request_id", "decision", "n_corrections", "created_at", "notes", "system_route",
                           "final_route", "route_overridden", "system_low_usd", "system_high_usd",
                           "final_low_usd", "final_high_usd", "estimate_overridden", "corrections"}


def test_reviews_endpoint_respects_limit():
    c = new_claim()
    for _ in range(4):
        review_post(c, decision="reject")
    assert len(client.get("/api/reviews?limit=3").json()["reviews"]) == 3
    assert len(client.get("/api/reviews").json()["reviews"]) == 4  # default 20


def test_reviews_endpoint_loads_old_rows(tmp_db):
    old = sqlite3.connect(tmp_db)  # pre-migration schema, as on the first deploy
    old.execute("CREATE TABLE reviews (id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL, "
                "decision TEXT NOT NULL, n_corrections INTEGER NOT NULL, created_at TEXT NOT NULL)")
    old.execute("CREATE TABLE corrections (id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL, field TEXT NOT NULL, "
                "original TEXT, corrected TEXT, created_at TEXT NOT NULL)")
    ts = "2026-11-10T04:22:55.197723+00:00"
    old.execute("INSERT INTO reviews (request_id, decision, n_corrections, created_at) VALUES ('old1', 'accept', 1, ?)", (ts,))
    old.execute("INSERT INTO corrections (request_id, field, original, corrected, created_at) VALUES ('old1', 'vehicle.model', 'Cirrus', 'Cirrus LX', ?)", (ts,))
    old.commit()
    old.close()
    (row,) = client.get("/api/reviews").json()["reviews"]
    assert row["notes"] is None and row["system_route"] is None and row["final_route"] is None and row["route_overridden"] is False
    assert row["corrections"] == [{"field": "vehicle.model", "original": "Cirrus", "corrected": "Cirrus LX"}]


def test_reviews_endpoint_requires_auth():
    assert TestClient(app).get("/api/reviews").status_code == 401
    assert client.get("/api/reviews").status_code == 200



# ---------- adjuster-set final estimate range ----------
def sev4_claim(monkeypatch):
    damage = [{"photo_index": 0, "panel": "fender", "side": "right", "damage_type": "deformation", "severity": 4,
               "confidence": "medium", "cues": "crushed"}]
    monkeypatch.setattr(pipeline, "call_model", lambda images, **kw: (
        ModelOutput.model_validate(model_output_dict(damage=damage)), UsageTally("claude-sonnet-5-5", 1000, 0, 0, 200, 1)))
    c = new_claim()
    assert c["cost"]["status"] == "not_estimable"
    return c


def sys_range(c):
    return round(c["cost"]["low_usd"]), round(c["cost"]["high_usd"])


@pytest.mark.parametrize("extra,what", [
    ({"final_low_usd": 500}, "both"),
    ({"final_high_usd": 900}, "both"),
    ({"final_low_usd": 900, "final_high_usd": 500}, "low must not be higher"),
])
def test_estimate_range_rule_errors(extra, what):
    c = new_claim()
    r = review_post(c, **unedited(c, **extra))
    assert r.status_code == 422 and what in r.json()["error"]
    assert client.get("/api/reviews").json()["reviews"] == []  # refused, nothing logged


@pytest.mark.parametrize("low,high", [(-1, 500), (0, 500_001), (10.5, 20)])
def test_estimate_range_bounds_and_whole_dollars(low, high):
    c = new_claim()
    r = review_post(c, **unedited(c, final_low_usd=low, final_high_usd=high))
    assert r.status_code == 422 and r.json()["error"] == "Invalid request."


def test_estimate_range_with_reject_is_refused():
    c = new_claim()
    r = review_post(c, decision="reject", final_low_usd=100, final_high_usd=200)
    assert r.status_code == 422 and "only allowed with accept" in r.json()["error"]


def test_estimate_override_stored_logged_and_does_not_reroute():
    c = new_claim()
    lo, hi = sys_range(c)
    r = review_post(c, **unedited(c, final_low_usd=lo + 50, final_high_usd=hi - 100)).json()
    assert r["estimate_overridden"] is True
    assert (r["system_low_usd"], r["system_high_usd"], r["final_low_usd"], r["final_high_usd"]) == (lo, hi, lo + 50, hi - 100)
    assert r["routing"] == c["routing"] and r["final_route"] == c["routing"]["outcome"] and r["cost"] == c["cost"]
    assert r["corrections"] == [{"field": "estimate.low", "original": str(lo), "corrected": str(lo + 50)},
                                {"field": "estimate.high", "original": str(hi), "corrected": str(hi - 100)}]
    row = client.get("/api/reviews").json()["reviews"][0]
    assert (row["system_low_usd"], row["system_high_usd"], row["final_low_usd"], row["final_high_usd"], row["estimate_overridden"]) == (
        lo, hi, lo + 50, hi - 100, True)
    assert row["n_corrections"] == 2 and {x["field"] for x in row["corrections"]} == {"estimate.low", "estimate.high"}


def test_untouched_range_is_not_an_override_even_after_repricing():
    c = new_claim()
    items = items_as_sent(c)
    items[0]["severity"] = 1  # a finding correction re-prices the claim
    r = review_post(c, **unedited(c, damage=items)).json()  # range fields not sent (null)
    assert r["estimate_overridden"] is False and r["cost"] != c["cost"]
    assert (r["system_low_usd"], r["system_high_usd"]) == sys_range(c)
    assert (r["final_low_usd"], r["final_high_usd"]) == (round(r["cost"]["low_usd"]), round(r["cost"]["high_usd"]))
    assert all(not x["field"].startswith("estimate.") for x in r["corrections"])


def test_sending_the_system_range_is_not_an_override():
    c = new_claim()
    lo, hi = sys_range(c)
    r = review_post(c, **unedited(c, final_low_usd=lo, final_high_usd=hi)).json()
    assert r["estimate_overridden"] is False and r["corrections"] == []


def test_estimate_override_on_a_not_estimable_claim(monkeypatch):
    c = sev4_claim(monkeypatch)
    r = review_post(c, **unedited(c, final_low_usd=3000, final_high_usd=8000)).json()
    assert r["estimate_overridden"] is True and r["system_low_usd"] is None and r["system_high_usd"] is None
    assert (r["final_low_usd"], r["final_high_usd"]) == (3000, 8000)
    assert {"field": "estimate.low", "original": "not estimable", "corrected": "3000"} in r["corrections"]
    assert r["routing"] == c["routing"] and r["cost"] == c["cost"]  # route and cost untouched by the range


def test_estimate_override_with_route_override_keeps_them_separate():
    c = new_claim()
    lo, hi = sys_range(c)
    r = review_post(c, **unedited(c, final_low_usd=lo, final_high_usd=hi + 1, final_route="possible_total_loss", notes="x")).json()
    assert r["estimate_overridden"] is True and r["route_overridden"] is True
    assert r["routing"] == c["routing"] and r["final_route"] == "possible_total_loss"
