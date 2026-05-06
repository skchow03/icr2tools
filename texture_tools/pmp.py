from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageFile, UnidentifiedImageError


def _load_rgba_image_with_tolerant_fallback(src: Path) -> Image.Image:
    """Load an image as RGBA from disk with strict-to-tolerant decoding fallbacks."""
    data = src.read_bytes()
    original_truncated_setting = ImageFile.LOAD_TRUNCATED_IMAGES

    def _decode_bytes(*, allow_truncated: bool) -> Image.Image:
        ImageFile.LOAD_TRUNCATED_IMAGES = allow_truncated
        with Image.open(BytesIO(data)) as image:
            image.load()
            return image.convert("RGBA").copy()

    try:
        return _decode_bytes(allow_truncated=False)
    except Exception:
        pass

    try:
        return _decode_bytes(allow_truncated=True)
    except Exception:
        pass

    try:
        ImageFile.LOAD_TRUNCATED_IMAGES = True
        parser = ImageFile.Parser()
        parser.feed(data)
        parsed = parser.close()
        parsed.load()
        return parsed.convert("RGBA").copy()
    except Exception as exc:
        message = str(exc).lower()
        is_png = src.suffix.lower() == ".png" or data.startswith(b"\x89PNG\r\n\x1a\n")
        if is_png and ("truncated" in message or "chunk" in message or len(data) < 64):
            raise ValueError(f"PNG appears truncated/corrupted: {exc}") from exc
        raise ValueError(f"Unable to decode image bytes: {exc}") from exc
    finally:
        ImageFile.LOAD_TRUNCATED_IMAGES = original_truncated_setting

DEFAULT_UNKNOWN_FIELD = bytes((0x1E, 0x00, 0x00, 0x00))


def _encode_runs(indexed: Image.Image, alpha: Image.Image | None = None, *, alpha_transparent_threshold: int = 0) -> bytes:
    width, height = indexed.size
    color_pixels = indexed.load()
    alpha_pixels = alpha.load() if alpha is not None else None
    data = bytearray()

    for y in range(height):
        x = 0
        while x < width:
            if alpha_pixels is not None and int(alpha_pixels[x, y]) <= alpha_transparent_threshold:
                x += 1
                continue

            color = int(color_pixels[x, y])
            start = x
            x += 1
            while x < width:
                if alpha_pixels is not None and int(alpha_pixels[x, y]) <= alpha_transparent_threshold:
                    break
                if int(color_pixels[x, y]) != color:
                    break
                x += 1
            end_exclusive = x
            data.extend((y, start, end_exclusive, color))
    return bytes(data)


def _quantize_with_palette(image: Image.Image, palette_path: str | Path | None) -> Image.Image:
    if palette_path is None:
        return image.convert("P")

    palette_img = Image.open(palette_path)
    try:
        return image.quantize(colors=256, method=Image.Quantize.FASTOCTREE, palette=palette_img)
    finally:
        palette_img.close()


def png_to_pmp(
    input_path: str | Path,
    output_path: str | Path,
    *,
    size_field: int,
    palette_path: str | Path | None = "SUNNY.PCX",
    unknown_field: bytes = DEFAULT_UNKNOWN_FIELD,
    alpha_transparent_threshold: int = 0,
) -> Path:
    """Convert an input PNG image to a PMP sprite file.

    Header layout emitted by this converter:
      - byte 0: sprite bounding-box width (0-255)
      - byte 1: sprite bounding-box height (0-255)
      - byte 2: signed int8 ``-left`` (pixels from image left edge to bbox left)
      - byte 3: signed int8 ``-top`` (pixels from image top edge to bbox top)
      - bytes 4-7: run data byte length (little-endian)
      - bytes 8-11: opaque 4-byte field (defaults to ``1E 00 00 00``)

    Run payload layout emitted by this converter:
      - 4 bytes per run: ``(y, x_start, x_end_exclusive, palette_index)``

    The PMP format here uses 8-bit indexed colors and stores image rows as
    runs of contiguous pixels of the same palette index.

    For backward compatibility, ``size_field`` can still be provided. When it
    is non-zero, bytes 2-3 are written directly from ``size_field`` as
    little-endian metadata instead of auto-computing signed bbox origin bytes.
    """
    src = Path(input_path)
    dst = Path(output_path)

    try:
        rgba = _load_rgba_image_with_tolerant_fallback(src)
        alpha = rgba.getchannel("A")
        indexed = _quantize_with_palette(rgba.convert("RGB"), palette_path)
        width, height = indexed.size

        if width > 256 or height > 256:
            raise ValueError("PMP only supports images up to 256x256 pixels")

        if len(unknown_field) != 4:
            raise ValueError("unknown_field must be exactly 4 bytes")

        if not 0 <= int(alpha_transparent_threshold) <= 255:
            raise ValueError("alpha_transparent_threshold must be in range 0..255")

        alpha_thresholded = alpha.point(lambda value: 0 if int(value) <= int(alpha_transparent_threshold) else 255)
        encoded_runs = _encode_runs(indexed, alpha, alpha_transparent_threshold=int(alpha_transparent_threshold))
        bbox = alpha_thresholded.getbbox()
    except (OSError, UnidentifiedImageError) as exc:
        suffix = src.suffix.lower()
        file_size = src.stat().st_size if src.exists() else 0
        raise ValueError(
            f"Unable to read input image '{src}'. {exc}. "
            f"File details: extension={suffix or '<none>'}, size={file_size} bytes. "
            "This usually means Pillow could not decode the PNG format variant. "
            "re-save it as a standard non-interlaced PNG and try again."
        ) from exc

    if bbox is None:
        bbox_width = 0
        bbox_height = 0
        bbox_left_margin_signed = 0
        bbox_top_margin_signed = 0
    else:
        left, top, right_exclusive, bottom_exclusive = bbox
        bbox_width = right_exclusive - left
        bbox_height = bottom_exclusive - top
        bbox_left_margin_signed = (-left) & 0xFF
        bbox_top_margin_signed = (-top) & 0xFF

    header = bytearray()
    header.extend((bbox_width % 256, bbox_height % 256))
    if int(size_field):
        header.extend(int(size_field).to_bytes(2, "little", signed=False))
    else:
        header.extend((bbox_left_margin_signed, bbox_top_margin_signed))
    header.extend(len(encoded_runs).to_bytes(4, "little", signed=False))
    header.extend(unknown_field)

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(bytes(header) + encoded_runs)
    return dst
