from __future__ import annotations

from pathlib import Path

from PIL import Image


DEFAULT_UNKNOWN_FIELD = bytes((0x1E, 0x00, 0x00, 0x00))


def _encode_runs(indexed: Image.Image, alpha: Image.Image | None = None) -> bytes:
    width, height = indexed.size
    color_pixels = indexed.load()
    alpha_pixels = alpha.load() if alpha is not None else None
    data = bytearray()

    for y in range(height):
        x = 0
        while x < width:
            if alpha_pixels is not None and int(alpha_pixels[x, y]) == 0:
                x += 1
                continue

            color = int(color_pixels[x, y])
            start = x
            x += 1
            while x < width:
                if alpha_pixels is not None and int(alpha_pixels[x, y]) == 0:
                    break
                if int(color_pixels[x, y]) != color:
                    break
                x += 1
            end = x - 1
            data.extend((y, start, end, color))
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
) -> Path:
    """Convert an input PNG image to a PMP sprite file.

    The PMP format uses 8-bit indexed colors and stores image rows as runs of
    contiguous pixels of the same palette index.
    """
    src = Path(input_path)
    dst = Path(output_path)

    with Image.open(src) as image:
        rgba = image.convert("RGBA")
        alpha = rgba.getchannel("A")
        indexed = _quantize_with_palette(rgba.convert("RGB"), palette_path)
        width, height = indexed.size

        if width > 256 or height > 256:
            raise ValueError("PMP only supports images up to 256x256 pixels")

        if len(unknown_field) != 4:
            raise ValueError("unknown_field must be exactly 4 bytes")

        encoded_runs = _encode_runs(indexed, alpha)

    header = bytearray()
    header.extend((height % 256, width % 256))
    header.extend(int(size_field).to_bytes(2, "little", signed=False))
    header.extend(len(encoded_runs).to_bytes(4, "little", signed=False))
    header.extend(unknown_field)

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(bytes(header) + encoded_runs)
    return dst
