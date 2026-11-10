"""Image intake: validate by magic bytes, guard against decompression bombs, normalize, hash.

Everything happens in memory. Original bytes are hashed, never stored.
"""

import hashlib
import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps

from app.config import settings


class IntakeError(ValueError):
    """Input rejected before any model call. Message is safe to show the user."""


# Accepted formats, identified by leading bytes (not by file extension or client MIME type).
_MAGIC = {
    "jpeg": (b"\xff\xd8\xff",),
    "png": (b"\x89PNG\r\n\x1a\n",),
}


def sniff_format(data: bytes) -> str:
    for fmt, prefixes in _MAGIC.items():
        if any(data.startswith(p) for p in prefixes):
            return fmt
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"mif1", b"heim"):
        raise IntakeError("HEIC/HEIF photos are not supported yet. Please send a JPEG or PNG.")
    raise IntakeError("Unsupported file type. Please send a JPEG, PNG or WebP photo.")


@dataclass
class PreparedImage:
    sha256: str  # hash of the ORIGINAL bytes (cache key, audit)
    jpeg_bytes: bytes  # normalized, resized, metadata-stripped JPEG sent to the model
    width: int  # after resize
    height: int
    image: Image.Image  # resized RGB image, for prechecks


def prepare_image(data: bytes) -> PreparedImage:
    if not data:
        raise IntakeError("Empty file.")
    if len(data) > settings.max_upload_bytes:
        raise IntakeError(f"File too large (max {settings.max_upload_bytes // (1024 * 1024)} MB).")
    sniff_format(data)

    sha = hashlib.sha256(data).hexdigest()
    Image.MAX_IMAGE_PIXELS = settings.max_image_pixels
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(data))
            w, h = img.size  # read from the header, before decoding pixels
            if w * h > settings.max_image_pixels or max(w, h) > settings.max_image_side_px:
                raise IntakeError("Image dimensions too large.")
            img.load()
    except IntakeError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise IntakeError("Image dimensions too large.")
    except Exception:
        raise IntakeError("File could not be decoded as an image.")

    img = ImageOps.exif_transpose(img)  # honor camera rotation, then drop EXIF (GPS etc.)
    img = img.convert("RGB")
    img.thumbnail((settings.model_image_long_side_px, settings.model_image_long_side_px))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)  # no exif= argument: metadata is not written
    return PreparedImage(sha256=sha, jpeg_bytes=buf.getvalue(), width=img.width, height=img.height, image=img)
