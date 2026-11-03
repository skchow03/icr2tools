"""Read-only ICR2 PMP sprite decoding for 3DO PMP/PMP2 nodes.

Observed from stock helmets and tree1..tree4 scenery:
    Bytes 0..3 are NOT a fixed magic signature. They encode the extents of
    the span records: (pixel_width, pixel_height, -min_x, -min_y), modulo
    256 for the origin offsets. For example, tree2 starts 5b 7b af fb,
    while tree1 starts 7a 79 be f9. Both describe valid PMP sprites.
    Byte 4: little-endian uint32 declared size.
    Byte 8: little-endian uint32 auxiliary field.
    Byte 12 onward: (y, x_start, x_end, palette_index) 4-byte records
    painting [x_start,x_end) on scanline y of a transparent 256x256 canvas.

    Stock helmet PMP files have an extra single 0xaf footer; tree scenery
    files end immediately after the final four-byte record. Framing is
    determined by record alignment, not by the variable extent bytes.
    Missing pixel spans remain transparent; palette index 0 is not alpha.
"""
from pathlib import Path
from dataclasses import dataclass
import struct


class PMPError(ValueError):
    pass


@dataclass(frozen=True)
class PMPSprite:
    path: Path
    # RGBA cropped to nontransparent spans; pixel anchor 128,128 in source canvas.
    rgba: object
    bounds: tuple[int, int, int, int]
    auxiliary: int


def load_pmp(path, palette):
    from PIL import Image

    path = Path(path)
    data = path.read_bytes()
    if len(data) < 16:
        raise PMPError(f'{path.name}: PMP header or color-span records truncated')

    # The old decoder incorrectly treated the four extent bytes as a
    # constant signature. Derive their meaning from the actual span bounds
    # instead. The footer is optional but, when present, must be 0xaf.
    if (len(data) - 12) % 4 == 0:
        spans_end = len(data)
    elif (len(data) - 13) % 4 == 0 and data[-1] == 0xaf:
        spans_end = len(data) - 1
    else:
        raise PMPError(f'{path.name}: malformed PMP color-span records')
    if spans_end <= 12:
        raise PMPError(f'{path.name}: no PMP color-span records')

    declared, auxiliary = struct.unpack_from('<II', data, 4)
    # Existing helmets, plus all four observed trees, use the payload length
    # excluding the 12-byte header; preserve previously supported alternatives.
    if declared not in (len(data)-12, len(data)-4, len(data)):
        raise PMPError(
            f'{path.name}: PMP size {declared} does not match {len(data)} bytes')
    if len(palette) != 256:
        raise PMPError('PMP requires 256 RGB palette colors')

    spans = []
    min_x = min_y = 256
    max_x = max_y = -1
    for k in range(12, spans_end, 4):
        y, x0, x1, color = data[k:k+4]
        if x1 < x0:
            raise PMPError(f'{path.name}: inverted color span at {k}')
        if x1 == x0:
            continue
        spans.append((y, x0, x1, color))
        min_x = min(min_x, x0)
        max_x = max(max_x, x1)
        min_y = min(min_y, y)
        max_y = max(max_y, y)

    if not spans:
        raise PMPError(f'{path.name}: no visible spans')
    expected_header = bytes((
        max_x - min_x,
        max_y - min_y + 1,
        (-min_x) & 0xff,
        (-min_y) & 0xff,
    ))
    if data[:4] != expected_header:
        raise PMPError(
            f'{path.name}: PMP extent header does not match color spans '
            f'(found {data[:4].hex()}, expected {expected_header.hex()})')

    rgba = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
    pix = rgba.load()
    for y, x0, x1, color in spans:
        rgb = tuple(palette[color])
        for x in range(x0, x1):
            pix[x, y] = rgb + (255,)
    bounds = (min_x, min_y, max_x, max_y + 1)
    return PMPSprite(path, rgba.crop(bounds), bounds, auxiliary)
