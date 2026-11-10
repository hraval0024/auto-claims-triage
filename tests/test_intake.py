import io

import pytest
from PIL import Image

from app import intake
from app.intake import IntakeError, prepare_image


def _img_bytes(fmt="JPEG", size=(800, 600), exif=None) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", size, "gray")
    kw = {"exif": exif} if exif else {}
    img.save(buf, format=fmt, **kw)
    return buf.getvalue()


def test_text_file_with_image_extension_rejected():
    with pytest.raises(IntakeError, match="Unsupported file type"):
        prepare_image(b"this is not an image, despite being called photo.jpg")


def test_heic_rejected_with_clear_message():
    fake_heic = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 32
    with pytest.raises(IntakeError, match="HEIC"):
        prepare_image(fake_heic)


def test_truncated_jpeg_rejected():
    with pytest.raises(IntakeError, match="could not be decoded"):
        prepare_image(_img_bytes()[:200])


def test_png_accepted_and_normalized_to_jpeg():
    out = prepare_image(_img_bytes("PNG"))
    assert out.jpeg_bytes.startswith(b"\xff\xd8\xff")


def test_resized_to_long_side_cap():
    out = prepare_image(_img_bytes(size=(4000, 3000)))
    assert max(out.width, out.height) == 1568


def test_decompression_bomb_rejected_before_decode(monkeypatch):
    monkeypatch.setattr(intake.settings, "max_image_pixels", 1_000_000)
    with pytest.raises(IntakeError, match="dimensions too large"):
        prepare_image(_img_bytes("PNG", size=(2000, 2000)))


def test_oversize_file_rejected(monkeypatch):
    monkeypatch.setattr(intake.settings, "max_upload_bytes", 1000)
    with pytest.raises(IntakeError, match="too large"):
        prepare_image(_img_bytes())


def test_exif_metadata_stripped():
    exif = Image.Exif()
    exif[0x010F] = "SecretCameraMaker"  # Make tag
    src = _img_bytes(exif=exif.tobytes())
    assert b"SecretCameraMaker" in src
    out = prepare_image(src)
    assert b"SecretCameraMaker" not in out.jpeg_bytes


def test_hash_is_of_original_bytes():
    import hashlib

    src = _img_bytes()
    assert prepare_image(src).sha256 == hashlib.sha256(src).hexdigest()
