import csv
from pathlib import Path

import pytest

from scripts import import_labels
from scripts.label_schema import CAMERA_VIEWS, DAMAGE_TYPES, DMG_COLS, GATE_BLOCKING, GATE_NONBLOCKING, LABEL_IMG_COLS, PANELS, SIDES

ROOT = Path(__file__).resolve().parent.parent
SRC = "ChatGPT (test); model-generated, not human-verified"


def write(path: Path, header: list[str], rows: list[list]) -> Path:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return path


def img(iid="eval_008", gate="yes", reason="", make="Acura", model="TSX", color="white", ys="2009", ye="2014",
        view="front_right", dmg="yes", notes=""):
    return [iid, gate, reason, make, model, color, ys, ye, view, dmg, notes]


def run(tmp_path, images, damage, *extra):
    i = write(tmp_path / "in_img.csv", LABEL_IMG_COLS, images)
    d = write(tmp_path / "in_dmg.csv", DMG_COLS, damage)
    out = tmp_path / "out"
    code = import_labels.main(["--images", str(i), "--damage", str(d), "--label-source", SRC, "--out-dir", str(out), *extra])
    return code, out


def rows(path):
    return list(csv.DictReader(open(path))) if path.exists() else []


@pytest.fixture(autouse=True)
def cwd_root(monkeypatch):
    monkeypatch.chdir(ROOT)  # manifest path is relative to the repo root


def test_valid_import_writes_rows_with_provenance(tmp_path):
    code, out = run(tmp_path, [img(), img("eval_024", dmg="no")], [["eval_008", "headlamp", "right", "shatter", "3", ""]])
    assert code == 0
    got = {r["image_id"]: r for r in rows(out / "images_labels.csv")}
    assert set(got) == {"eval_008", "eval_024"}
    assert got["eval_008"]["commons_title"] == "File:Oh deer!.jpg" and got["eval_008"]["label_source"] == SRC
    assert len(rows(out / "damage_labels.csv")) == 1
    assert "Manifest images with no label row: 32" in (out / "import_report.txt").read_text()


def test_bad_value_rejects_whole_image_and_is_reported(tmp_path, capsys):
    code, out = run(tmp_path, [img(), img("eval_024", dmg="no")],
                    [["eval_008", "headlamp", "Right", "shatter", "3", ""],  # wrong case: not silently fixed
                     ["eval_008", "front_bumper", "right", "crack", "3", ""]])
    assert code == 1
    assert [r["image_id"] for r in rows(out / "images_labels.csv")] == ["eval_024"]
    assert rows(out / "damage_labels.csv") == []  # the valid bumper row went too: no partial labels
    assert "side 'Right' not allowed" in capsys.readouterr().out


@pytest.mark.parametrize("row, msg", [
    (img(gate="maybe"), "should_pass_gate"),
    (img(gate="no", reason=""), "needs gate_reason"),
    (img(gate="no", reason="embedded_instruction_text"), "needs gate_reason"),
    (img(gate="yes", reason="not_a_vehicle"), "allows gate_reason"),
    (img(make=""), "make is empty"),
    (img(ys="2014", ye="2009"), "start <= end"),
    (img(ys="2009", ye=""), "both be filled"),
    (img(ys="2009.5", ye="2010"), "whole numbers"),
    (img(view="top"), "camera_view"),
    (img(dmg="y"), "has_visible_damage"),
])
def test_image_rule_violations(tmp_path, capsys, row, msg):
    code, out = run(tmp_path, [row], [["eval_008", "headlamp", "right", "shatter", "3", ""]])
    assert code == 1 and rows(out / "images_labels.csv") == []
    assert msg in capsys.readouterr().out


def test_consistency_rules(tmp_path, capsys):
    code, _ = run(tmp_path, [img("eval_008", dmg="no"), img("eval_024", dmg="yes")], [["eval_008", "hood", "center", "dent", "2", ""]])
    out = capsys.readouterr().out
    assert "has_visible_damage=no but 1 damage row" in out and "but no damage rows" in out and code == 1


def test_gate_fail_with_reason_and_no_damage_is_valid(tmp_path):
    code, out = run(tmp_path, [img("eval_016", gate="no", reason="multiple_vehicles", make="unknown", model="unknown",
                                   color="unknown", ys="", ye="", view="not_applicable", dmg="yes")], [])
    assert code == 0 and rows(out / "images_labels.csv")[0]["gate_reason"] == "multiple_vehicles"


def test_whitespace_trimmed_and_announced(tmp_path):
    code, out = run(tmp_path, [img(make="  Acura ")], [["eval_008", " headlamp", "right", "shatter", "3", ""]])
    assert code == 0 and rows(out / "images_labels.csv")[0]["make"] == "Acura"
    assert "whitespace trimmed" in (out / "import_report.txt").read_text()


def test_removed_unknown_duplicate_and_orphan_rows_reported(tmp_path, capsys):
    code, out = run(tmp_path, [img("eval_007"), img("eval_999"), img(), img()],
                    [["eval_031", "front_bumper", "center", "scratch_scuff", "1", ""], ["eval_008", "headlamp", "right", "shatter", "3", ""]])
    o = capsys.readouterr().out
    assert "eval_007 was removed" in o and "unknown image_id 'eval_999'" in o and "duplicate image row" in o and "no image row" in o
    assert rows(out / "images_labels.csv") == [] and code == 1


def test_wrong_header_rejects_file(tmp_path, capsys):
    i = write(tmp_path / "bad.csv", ["image_id", "gate_expected"], [["eval_008", "pass"]])
    d = write(tmp_path / "d.csv", DMG_COLS, [])
    import_labels.main(["--images", str(i), "--damage", str(d), "--label-source", SRC, "--out-dir", str(tmp_path / "o")])
    assert "header must be exactly" in capsys.readouterr().out


def test_dry_run_writes_nothing_and_existing_labels_need_replace(tmp_path):
    code, out = run(tmp_path, [img()], [["eval_008", "headlamp", "right", "shatter", "3", ""]], "--dry-run")
    assert not (out / "images_labels.csv").exists()
    run(tmp_path, [img()], [["eval_008", "headlamp", "right", "shatter", "3", ""]])
    code, _ = run(tmp_path, [img(make="Honda")], [["eval_008", "headlamp", "right", "shatter", "3", ""]])
    assert code == 2 and rows(out / "images_labels.csv")[0]["make"] == "Acura"
    code, _ = run(tmp_path, [img(make="Honda")], [["eval_008", "headlamp", "right", "shatter", "3", ""]], "--replace")
    assert code == 0 and rows(out / "images_labels.csv")[0]["make"] == "Honda"


def test_blank_template_does_not_block_first_import(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "images_labels.csv").write_text((ROOT / "eval/labels/images_labels.csv").read_text())
    (out / "damage_labels.csv").write_text((ROOT / "eval/labels/damage_labels.csv").read_text())
    code, _ = run(tmp_path, [img()], [["eval_008", "headlamp", "right", "shatter", "3", ""]])
    assert code == 0


def test_vocab_md_lists_every_allowed_value():
    vocab = (ROOT / "eval/labels/VOCAB.md").read_text()
    for v in PANELS + SIDES + DAMAGE_TYPES + CAMERA_VIEWS + GATE_BLOCKING + GATE_NONBLOCKING:
        assert f"`{v}`" in vocab, v  # every allowed value, exactly as written
    import re
    for col in LABEL_IMG_COLS + DMG_COLS:
        assert re.search(rf"\b{col}\b", vocab), col


def test_chatgpt_prompt_matches_schema_and_hides_sources():
    p = (ROOT / "eval/labels/chatgpt_prompt.md").read_text()
    assert ",".join(LABEL_IMG_COLS) in p and ",".join(DMG_COLS) in p
    for v in PANELS + SIDES + DAMAGE_TYPES + CAMERA_VIEWS + GATE_BLOCKING + GATE_NONBLOCKING:
        assert v in p, v
    import json
    for e in json.load(open(ROOT / "eval/manifest.json"))["images"]:  # no titles, authors or links
        assert e["commons_title"][5:-4] not in p and "commons.wikimedia" not in p
