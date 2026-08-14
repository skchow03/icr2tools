from __future__ import annotations

from pathlib import Path

from PyQt5 import QtGui


def load_qimage(path: str | Path) -> QtGui.QImage:
    """Load an image for Qt, decoding PCX files unsupported by Qt directly."""
    resolved_path = Path(path)
    image = QtGui.QImage(str(resolved_path))
    if not image.isNull() or resolved_path.suffix.lower() != ".pcx":
        return image

    try:
        pixels, width, height = _decode_pcx(resolved_path.read_bytes())
    except (OSError, ValueError):
        return image

    # Detach the QImage from the temporary Python byte buffer before returning.
    return QtGui.QImage(
        pixels,
        width,
        height,
        width * 4,
        QtGui.QImage.Format_RGBA8888,
    ).copy()


def _decode_pcx(data: bytes) -> tuple[bytes, int, int]:
    """Decode the 8-bit indexed and 24-bit PCX variants used for backgrounds."""
    if len(data) < 128 or data[0] != 0x0A or data[2] not in (0, 1):
        raise ValueError("Invalid PCX header")

    bits_per_pixel = data[3]
    width = int.from_bytes(data[8:10], "little") - int.from_bytes(data[4:6], "little") + 1
    height = int.from_bytes(data[10:12], "little") - int.from_bytes(data[6:8], "little") + 1
    planes = data[65]
    bytes_per_line = int.from_bytes(data[66:68], "little")
    if bits_per_pixel != 8 or planes not in (1, 3) or min(width, height, bytes_per_line) <= 0:
        raise ValueError("Unsupported PCX layout")

    required = height * planes * bytes_per_line
    decoded = bytearray()
    offset = 128
    while len(decoded) < required and offset < len(data):
        value = data[offset]
        offset += 1
        if data[2] == 1 and value & 0xC0 == 0xC0:
            count = value & 0x3F
            if offset >= len(data):
                raise ValueError("Truncated PCX run")
            value = data[offset]
            offset += 1
        else:
            count = 1
        decoded.extend(bytes((value,)) * min(count, required - len(decoded)))
    if len(decoded) != required:
        raise ValueError("Truncated PCX image")

    if planes == 1:
        if len(data) < 769 or data[-769] != 0x0C:
            raise ValueError("Missing PCX palette")
        palette = data[-768:]

    rgba = bytearray(width * height * 4)
    for y in range(height):
        row_start = y * planes * bytes_per_line
        for x in range(width):
            if planes == 1:
                palette_offset = decoded[row_start + x] * 3
                red, green, blue = palette[palette_offset : palette_offset + 3]
            else:
                red = decoded[row_start + x]
                green = decoded[row_start + bytes_per_line + x]
                blue = decoded[row_start + 2 * bytes_per_line + x]
            target = (y * width + x) * 4
            rgba[target : target + 4] = bytes((red, green, blue, 255))
    return bytes(rgba), width, height
