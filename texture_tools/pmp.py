from __future__ import annotations

from pathlib import Path

from PIL import Image


DEFAULT_UNKNOWN_FIELD = bytes((0x1E, 0x00, 0x00, 0x00))


def _encode_runs(indexed: Image.Image) -> bytes:
    width, height = indexed.size
    pixels = indexed.load()
    data = bytearray()

    for y in range(height):
        x = 0
        while x < width:
            color = int(pixels[x, y])
            start = x
            x += 1
            while x < width and int(pixels[x, y]) == color:
                x += 1
            end = x - 1
            data.extend((y, start, end, color))
    return bytes(data)


def png_to_pmp(
    input_path: str | Path,
    output_path: str | Path,
    *,
    size_field: int,
    unknown_field: bytes = DEFAULT_UNKNOWN_FIELD,
) -> Path:
    """Convert an input PNG image to a PMP sprite file.

    The PMP format uses 8-bit indexed colors and stores image rows as runs of
    contiguous pixels of the same palette index.
    """
    src = Path(input_path)
    dst = Path(output_path)

    with Image.open(src) as image:
        indexed = image.convert("P")
        width, height = indexed.size

        if width > 255 or height > 255:
            raise ValueError("PMP only supports images up to 255x255 pixels")

        if len(unknown_field) != 4:
            raise ValueError("unknown_field must be exactly 4 bytes")

        encoded_runs = _encode_runs(indexed)

    header = bytearray()
    header.extend((height, width))
    header.extend(int(size_field).to_bytes(2, "little", signed=False))
    header.extend(len(encoded_runs).to_bytes(4, "little", signed=False))
    header.extend(unknown_field)

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(bytes(header) + encoded_runs)
    return dst
