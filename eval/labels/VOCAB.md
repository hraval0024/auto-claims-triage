# Label vocabulary

Values must match exactly (lower case, as written). They match the API schema
(`app/schemas.py`) and are enforced by `scripts/import_labels.py`.

**Provenance:** every row records `label_source`, set on import. Labels from ChatGPT are
model-generated and not human-verified; the eval reports them as agreement with those labels,
not as accuracy.

## images_labels.csv: one row per image

| Column | Allowed values |
|---|---|
| image_id | `eval_XXX` (the file name without `.jpg`) |
| should_pass_gate | `yes` (the photo can be assessed) or `no` |
| gate_reason | If should_pass_gate = `no`: required, one of `bad_angle_or_crop`, `damage_area_not_visible`, `likely_screenshot_or_stock`, `multiple_vehicles`, `not_a_vehicle`, `too_blurry_or_dark`. If should_pass_gate = `yes`: empty, or `embedded_instruction_text` (text in the photo that addresses an AI; flagged but does not block). |
| make, model, color | Free text, or `unknown`. Never empty. |
| year_start, year_end | Whole years 1900-2027, both filled or both empty; start ≤ end |
| camera_view | `front`, `rear`, `left_side`, `right_side`, `front_left`, `front_right`, `rear_left`, `rear_right`, `close_up_unclear`, `not_applicable` (no vehicle) |
| has_visible_damage | `yes` or `no` |
| label_notes | Free text, may be empty |

## damage_labels.csv: one row per damaged part (none if undamaged)

| Column | Allowed values |
|---|---|
| image_id | must have a row in images_labels.csv |
| panel | `front_bumper`, `rear_bumper`, `grille`, `hood`, `roof`, `trunk_tailgate`, `fender`, `front_door`, `rear_door`, `quarter_panel`, `rocker_panel`, `pillar`, `headlamp`, `taillamp`, `side_mirror`, `windshield`, `rear_glass`, `side_glass`, `wheel`, `tire`, `other_unknown` |
| side | `left`, `right`, `center`, `unknown` (the vehicle's own side, see below) |
| damage_type | `scratch_scuff`, `dent`, `crack`, `shatter`, `deformation`, `tear_puncture`, `missing_part`, `misalignment` |
| severity | `1`, `2`, `3`, `4` (see `app/prompts/rubric_v1.md`) |
| label_notes | Free text, may be empty |

## Consistency rules (checked on import)

- has_visible_damage = `no` → no damage rows for that image.
- has_visible_damage = `yes` and should_pass_gate = `yes` → at least one damage row.
- The same (panel, side, damage_type) at most once per image.
- If any row for an image is invalid, the whole image (its image row and all its damage rows) is rejected and reported, so partial labels never bias recall.
