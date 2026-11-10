import io

from PIL import Image, ImageDraw


def model_output_dict(n_photos=1, issues=None, damage=None, makes=None, colors=None) -> dict:
    """A schema-valid ModelOutput payload for tests (synthetic, not a real model response)."""
    issues = issues or {}
    makes = makes or ["Toyota"] * n_photos
    colors = colors or ["silver"] * n_photos
    return {
        "photos": [
            {
                "photo_index": i,
                "camera_view": "rear_left",
                "issues": issues.get(i, []),
                "retake_advice": "Send a daylight photo of the damaged side." if issues.get(i) else "",
                "vehicle_make_seen": makes[i],
                "vehicle_color_seen": colors[i],
                "license_plate_visible": False,
                "person_face_visible": False,
                "embedded_text_seen": "",
            }
            for i in range(n_photos)
        ],
        "vehicle": {
            "make": {"value": "Toyota", "confidence": "high"},
            "model": {"value": "Corolla", "confidence": "medium"},
            "color": {"value": "silver", "confidence": "high"},
            "year_range": {"start": 2014, "end": 2018, "confidence": "low"},
        },
        "damage": damage
        if damage is not None
        else [
            {"photo_index": 0, "panel": "rear_bumper", "side": "left", "damage_type": "dent",
             "severity": 2, "confidence": "high", "cues": "smooth dent, paint intact"}
        ],
        "damage_summary": "Left rear bumper dent.",
        "not_assessable": ["underbody"],
    }


def textured_jpeg(size=(800, 600)) -> bytes:
    """A bright, edge-rich synthetic image that passes the deterministic prechecks."""
    img = Image.new("RGB", size, (180, 180, 180))
    d = ImageDraw.Draw(img)
    for x in range(0, size[0], 20):
        d.line([(x, 0), (x, size[1])], fill=(20, 20, 20), width=3)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def black_jpeg(size=(800, 600)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (0, 0, 0)).save(buf, format="JPEG")
    return buf.getvalue()
