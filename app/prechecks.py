"""Cheap deterministic photo checks that run before the model call.

Only extreme values block (no point paying for a model call on a black frame or a thumbnail).
Milder values are warnings shown to the adjuster; they are NOT sent to the model, so they
can't anchor its judgment. Every threshold is an ASSUMPTION, untuned until measured.
"""

from PIL import ImageFilter, ImageStat

from app.intake import PreparedImage
from app.schemas import PrecheckResult

# ASSUMPTIONS (untuned): thresholds on the resized grayscale image.
MIN_SHORT_SIDE_PX = 320  # below this, damage detail is not resolvable -> block
BLOCK_BRIGHTNESS_BELOW = 15.0  # mean 0-255; essentially a black frame -> block
WARN_BRIGHTNESS_BELOW = 50.0
WARN_SHARPNESS_BELOW = 60.0  # variance of the edge-filtered image; low = blurry


def run_prechecks(index: int, img: PreparedImage) -> PrecheckResult:
    gray = img.image.convert("L")
    brightness = ImageStat.Stat(gray).mean[0]
    sharpness = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).var[0]

    warnings, blocking = [], []
    if min(img.width, img.height) < MIN_SHORT_SIDE_PX:
        blocking.append(f"Photo {index} is too small ({img.width}x{img.height}); send the original photo.")
    if brightness < BLOCK_BRIGHTNESS_BELOW:
        blocking.append(f"Photo {index} is almost completely dark; retake it in daylight or with a light.")
    elif brightness < WARN_BRIGHTNESS_BELOW:
        warnings.append(f"Photo {index} is dark (mean brightness {brightness:.0f}/255).")
    if sharpness < WARN_SHARPNESS_BELOW:
        warnings.append(f"Photo {index} may be blurry (edge variance {sharpness:.0f}).")

    return PrecheckResult(
        photo_index=index,
        width=img.width,
        height=img.height,
        brightness_mean=round(brightness, 1),
        sharpness=round(sharpness, 1),
        warnings=warnings,
        blocking=blocking,
    )
