from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageFile, UnidentifiedImageError


DEFAULT_UNKNOWN_FIELD = bytes((0x1E, 0x00, 0x00, 0x00))


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
        raise ValueError(
            f"Unable to decode image with Pillow: {exc}. "
            "The image may be valid but use a PNG variant, chunk layout, color profile, "
            "or interlacing mode that this Pillow version rejects. "
            "Try re-exporting from GIMP as a non-interlaced 8-bit RGBA PNG."
        ) from exc
    finally:
        ImageFile.LOAD_TRUNCATED_IMAGES = original_truncated_setting


def _encode_runs(
    indexed: Image.Image,
    alpha: Image.Image | None = None,
    *,
    alpha_transparent_threshold: int = 0,
) -> bytes:
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


def _quantize_with_palette(image: Image.Image, palette_path: str | Path | None, *, dither: bool = False) -> Image.Image:
    if palette_path is None:
        dither_mode = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
        return image.convert("P", dither=dither_mode)

    palette_file = Path(palette_path)
    decode_error: Exception | None = None

    try:
        with Image.open(palette_file) as palette_img:
            dither_mode = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
            return image.quantize(colors=256, method=Image.Quantize.FASTOCTREE, palette=palette_img, dither=dither_mode)
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        decode_error = exc

    if palette_file.suffix.lower() != ".pcx":
        raise ValueError(f"Pillow failed to decode palette image: {decode_error}") from decode_error

    try:
        fallback_palette = _load_palette_from_pcx_trailer(palette_file)
        dither_mode = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
        return image.quantize(colors=256, method=Image.Quantize.FASTOCTREE, palette=fallback_palette, dither=dither_mode)
    except Exception as fallback_exc:
        raise ValueError(
            "Pillow failed to decode PCX palette and trailer extraction also failed: "
            f"{fallback_exc}"
        ) from decode_error



def _load_palette_from_pcx_trailer(path: Path) -> Image.Image:
    data = path.read_bytes()
    if len(data) < 769:
        raise ValueError(f"invalid palette trailer: file too short ({len(data)} bytes)")

    trailer = data[-769:]
    if trailer[0] != 0x0C:
        raise ValueError(
            f"invalid palette trailer: expected marker 0x0C, found 0x{trailer[0]:02X}"
        )

    palette_values = list(trailer[1:])
    pal_img = Image.new("P", (1, 1))
    pal_img.putpalette(palette_values)
    return pal_img

def _rgba_to_clean_rgb(rgba: Image.Image) -> Image.Image:
    """Flatten RGBA into a clean RGB image without carrying PNG metadata/chunks forward."""
    rgba = rgba.convert("RGBA").copy()
    rgb = Image.new("RGB", rgba.size, (0, 0, 0))
    rgb.paste(rgba, mask=rgba.getchannel("A"))
    return rgb


def png_to_pmp(
    input_path: str | Path,
    output_path: str | Path,
    *,
    size_field: int,
    palette_path: str | Path | None = "SUNNY.PCX",
    unknown_field: bytes = DEFAULT_UNKNOWN_FIELD,
    alpha_transparent_threshold: int = 0,
    dither: bool = False,
) -> Path:
    """Convert an input PNG image to a PMP sprite file.

    Header layout emitted by this converter:
      - byte 0: sprite bounding-box width (0-255)
      - byte 1: sprite bounding-box height (0-255)
      - byte 2: signed int8 ``-left`` (pixels from image left edge to bbox left)
      - byte 3: signed int8 ``-top`` (pixels from image top edge to bbox top)
      - bytes 4-7: run data byte length (little-endian)
      - bytes 8-11: opaque 4-byte field

    Run payload layout emitted by this converter:
      - 4 bytes per run: ``(y, x_start, x_end_exclusive, palette_index)``
    """
    src = Path(input_path)
    dst = Path(output_path)

    try:
        rgba = _load_rgba_image_with_tolerant_fallback(src)
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        suffix = src.suffix.lower()
        file_size = src.stat().st_size if src.exists() else 0
        raise ValueError(
            f"Unable to read input image '{src}'. {exc}. "
            f"File details: extension={suffix or '<none>'}, size={file_size} bytes. "
            "This usually means Pillow could not decode this image variant, "
            "not necessarily that the PNG is bad."
        ) from exc

    alpha = rgba.getchannel("A")
    rgb = _rgba_to_clean_rgb(rgba)

    try:
        indexed = _quantize_with_palette(rgb, palette_path, dither=dither)
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise ValueError(
            f"Unable to quantize image with palette '{palette_path}'. {exc}. "
            "Check that the palette file exists and is a valid PCX or another palette source supported by Pillow."
        ) from exc

    width, height = indexed.size

    if width > 256 or height > 256:
        raise ValueError("PMP only supports images up to 256x256 pixels")

    if len(unknown_field) != 4:
        raise ValueError("unknown_field must be exactly 4 bytes")

    threshold = int(alpha_transparent_threshold)
    if not 0 <= threshold <= 255:
        raise ValueError("alpha_transparent_threshold must be in range 0..255")

    alpha_thresholded = alpha.point(lambda value: 0 if int(value) <= threshold else 255)
    encoded_runs = _encode_runs(indexed, alpha, alpha_transparent_threshold=threshold)
    bbox = alpha_thresholded.getbbox()

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