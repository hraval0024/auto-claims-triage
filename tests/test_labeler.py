"""Labeling page backend: saves to the two CSVs, hides titles, rejects bad values."""

import csv
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from labeler import server

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client(tmp_path, monkeypatch):
    shutil.copy(ROOT / "eval/labels/images_labels.csv", tmp_path / "img.csv")
    monkeypatch.setitem(server.CFG, "images_csv", tmp_path / "img.csv")
    monkeypatch.setitem(server.CFG, "damage_csv", tmp_path / "dmg.csv")
    return TestClient(server.app)


GOOD = {"label_source": "candidate (not an adjuster)", "gate_expected": "pass", "make": "Acura", "model": "TSX",
        "color": "white", "year_start": 2009, "year_end": 2014, "camera_view": "front_right", "has_visible_damage": "y",
        "label_notes": "", "damage": [{"panel": "headlamp", "side": "right", "damage_type": "shatter", "severity": 3},
                                      {"panel": "front_bumper", "side": "right", "damage_type": "crack", "severity": 3}]}


def test_save_and_reload_round_trip(client):
    assert client.post("/api/labels/eval_008", json=GOOD).status_code == 200
    got = client.get("/api/labels/eval_008").json()
    assert got["make"] == "Acura" and got["year_end"] == "2014" and len(got["damage"]) == 2
    rows = list(csv.DictReader(open(server.CFG["images_csv"])))
    r = next(x for x in rows if x["image_id"] == "eval_008")
    assert r["commons_title"] == "File:Oh deer!.jpg" and r["license"] == "Public domain"  # provenance kept in the file
    assert len(rows) == 30


def test_resave_replaces_damage_rows_not_appends(client):
    client.post("/api/labels/eval_008", json=GOOD)
    client.post("/api/labels/eval_008", json=GOOD | {"damage": GOOD["damage"][:1]})
    dmg = list(csv.DictReader(open(server.CFG["damage_csv"])))
    assert len([d for d in dmg if d["image_id"] == "eval_008"]) == 1


def test_titles_and_sources_never_reach_the_page(client):
    client.post("/api/labels/eval_008", json=GOOD)
    blob = json.dumps(client.get("/api/labels/eval_008").json()) + json.dumps(client.get("/api/ids").json())
    assert "Oh deer" not in blob and "commons" not in blob.lower() and "Nyttend" not in blob


@pytest.mark.parametrize("bad", [
    {"damage": [{"panel": "spoiler", "side": "left", "damage_type": "dent", "severity": 2}]},
    {"damage": [{"panel": "hood", "side": "left", "damage_type": "dent", "severity": 5}]},
    {"gate_expected": "looks_fine"},
    {"camera_view": "top"},
    {"has_visible_damage": "maybe"},
    {"year_start": 2015, "year_end": 2010},
])
def test_invalid_values_rejected_and_nothing_written(client, bad):
    before = Path(server.CFG["images_csv"]).read_text()
    assert client.post("/api/labels/eval_008", json=GOOD | bad).status_code == 422
    assert Path(server.CFG["images_csv"]).read_text() == before


def test_unknown_or_traversal_ids_rejected(client):
    assert client.get("/api/image/..%2F..%2F.env").status_code == 404
    assert client.get("/api/image/eval_999").status_code == 404
    assert client.post("/api/labels/eval_999", json=GOOD).status_code == 404


def test_fresh_labeler_file_starts_from_manifest(tmp_path, monkeypatch):
    monkeypatch.setitem(server.CFG, "images_csv", tmp_path / "labeler_b_images.csv")
    monkeypatch.setitem(server.CFG, "damage_csv", tmp_path / "labeler_b_damage.csv")
    c = TestClient(server.app)
    assert c.post("/api/labels/eval_008", json=GOOD | {"label_source": "labeler B"}).status_code == 200
    rows = list(csv.DictReader(open(tmp_path / "labeler_b_images.csv")))
    assert rows[0]["image_id"] == "eval_008" and rows[0]["label_source"] == "labeler B"


def test_real_label_files_untouched_by_tests():
    rows = list(csv.DictReader(open(ROOT / "eval/labels/images_labels.csv")))
    assert all(r["make"] == "" and r["gate_expected"] == "" for r in rows)
    assert not list(csv.DictReader(open(ROOT / "eval/labels/damage_labels.csv")))
