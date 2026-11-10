# Label vocabulary

Use exactly these values (they match the API schema). Labels come from the candidate, not an
adjuster. Do not copy anything from model output.

- **images_labels.csv, one row per image.** `gate_expected`: `pass` or one of not_a_vehicle, multiple_vehicles, too_blurry_or_dark, damage_area_not_visible, bad_angle_or_crop, likely_screenshot_or_stock, embedded_instruction_text. `has_visible_damage`: `y` / `n`. Leave a field empty if you can't tell. `unknown` is allowed for make/model/color.
- **camera_view:** front, rear, left_side, right_side, front_left, front_right, rear_left, rear_right, close_up_unclear, not_applicable
- **damage_labels.csv, one row per damaged part.** Several rows per image are fine; none if undamaged.
- **panel:** front_bumper, rear_bumper, grille, hood, roof, trunk_tailgate, fender, front_door, rear_door, quarter_panel, rocker_panel, pillar, headlamp, taillamp, side_mirror, windshield, rear_glass, side_glass, wheel, tire, other_unknown
- **side (the vehicle's own side):** left, right, center, unknown
- **damage_type:** scratch_scuff, dent, crack, shatter, deformation, tear_puncture, missing_part, misalignment
- **severity:** 1-4, per app/prompts/rubric_v1.md
