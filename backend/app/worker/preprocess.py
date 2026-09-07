"""Worker stage 1 — preprocess (spec §4.3).

Pull the original from object storage, prove it decodes, strip EXIF, correct
orientation, and emit a normalised working copy plus a thumbnail under the
§5.7 key layout.
"""
import hashlib
import io
import logging
from dataclasses import dataclass
from typing import Tuple

from PIL import Image, ImageOps, UnidentifiedImageError

from ..config import get_settings

logger = logging.getLogger("stylesignal.worker.preprocess")

settings = get_settings()

# Decompression-bomb guard. Pillow's own limit is generous; uploads are capped
# at 1600px on the long edge by the client (§4.1) and re-capped here.
Image.MAX_IMAGE_PIXELS = 64_000_000

WORKING_JPEG_QUALITY = 88
THUMB_JPEG_QUALITY = 80


class UndecodableImage(Exception):
    """Maps to the ``undecodable`` failure reason (§5.3)."""


@dataclass
class PreprocessResult:
    working_bytes: bytes
    thumb_bytes: bytes
    working_image: Image.Image
    image_sha256: str
    width: int
    height: int


def preprocess(original: bytes) -> PreprocessResult:
    image = _open_and_normalise(original)

    working = _fit(image, settings.max_longest_edge)
    working_bytes = _encode_jpeg(working, WORKING_JPEG_QUALITY)

    thumb = _fit(working, settings.thumb_longest_edge)
    thumb_bytes = _encode_jpeg(thumb, THUMB_JPEG_QUALITY)

    # Hash the *normalised* bytes, not the upload: two uploads of the same
    # photo at different JPEG qualities should share a cache entry (§8).
    digest = hashlib.sha256(working_bytes).hexdigest()

    return PreprocessResult(
        working_bytes=working_bytes,
        thumb_bytes=thumb_bytes,
        working_image=working,
        image_sha256=digest,
        width=working.width,
        height=working.height,
    )


def _open_and_normalise(data: bytes) -> Image.Image:
    if not data:
        raise UndecodableImage("empty upload")
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise UndecodableImage(str(exc)) from exc

    # Rotate per the EXIF orientation tag, then drop EXIF entirely — it can
    # carry GPS coordinates, and §8 treats these images as personal data.
    image = ImageOps.exif_transpose(image)

    if image.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        converted = image.convert("RGBA")
        background.paste(converted, mask=converted.split()[-1])
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")

    # Flatten to a clean RGB image with no residual metadata/palette. Doing
    # this via list(image.getdata()) allocated one Python tuple object per
    # pixel (~9M for a real 4000x2252 phone photo) — hundreds of MB of pure
    # object overhead, enough on its own to exceed a Render worker's memory
    # limit regardless of job concurrency (docs/spec-deviations.md #27/#28).
    # Copying the raw byte buffer instead costs roughly the image's actual
    # pixel-data size (~27MB for that same photo), not a multiple of it.
    stripped = Image.frombytes("RGB", image.size, image.tobytes())
    return stripped


def _fit(image: Image.Image, longest_edge: int) -> Image.Image:
    if max(image.size) <= longest_edge:
        return image.copy()
    scale = longest_edge / float(max(image.size))
    target: Tuple[int, int] = (
        max(1, int(round(image.width * scale))),
        max(1, int(round(image.height * scale))),
    )
    return image.resize(target, Image.Resampling.LANCZOS)


def _encode_jpeg(image: Image.Image, quality: int) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()
