"""Eval label schema: one definition shared by the importer, the labeler and VOCAB.md.

Allowed values come from the API schema enums (app/schemas.py), so labels and model output
use exactly the same vocabulary.
"""

from app.schemas import BLOCKING_GATE_CODES, CameraView, DamageType, GateCode, Panel, Side

# Columns the external labeler (ChatGPT) outputs. Provenance columns are added on import.
LABEL_IMG_COLS = ["image_id", "should_pass_gate", "gate_reason", "make", "model", "color",
                  "year_start", "year_end", "camera_view", "has_visible_damage", "label_notes"]
DMG_COLS = ["image_id", "panel", "side", "damage_type", "severity", "label_notes"]
# Columns stored in eval/labels/images_labels.csv.
PROVENANCE_COLS = ["commons_title", "license", "author", "label_source"]
IMG_COLS = ["image_id"] + PROVENANCE_COLS + LABEL_IMG_COLS[1:]

YES_NO = ["yes", "no"]
GATE_BLOCKING = sorted(g.value for g in BLOCKING_GATE_CODES)  # should_pass_gate = no
GATE_NONBLOCKING = [GateCode.embedded_instruction_text.value]  # allowed with should_pass_gate = yes
CAMERA_VIEWS = [c.value for c in CameraView]
PANELS = [p.value for p in Panel]
SIDES = [s.value for s in Side]
DAMAGE_TYPES = [d.value for d in DamageType]
SEVERITIES = ["1", "2", "3", "4"]
YEAR_MIN, YEAR_MAX = 1900, 2027
