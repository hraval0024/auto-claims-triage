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
