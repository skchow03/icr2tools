"""Read-only ICR2 PMP sprite decoding for 3DO PMP/PMP2 nodes.

Observed from stock helmets and tree1..tree4 scenery:
    Bytes 0..3 are NOT a fixed magic signature. They encode nominal
    sprite placement extents: (width, height, -left, -top), modulo 256 for
    origin offsets. These are not always exact painted bounds: some helmet
    spans extend slightly beyond their nominal rectangle; all four observed
    trees happen to match it. Tree2 starts 5b 7b af fb; tree1 starts
    7a 79 be f9. Both describe valid PMP sprites.
    Byte 4: little-endian uint32 declared size.
    Byte 8: little-endian uint32 auxiliary field.
    Byte 12 onward: (y, x_start, x_end, palette_index) 4-byte records
    painting [x_start,x_end) on scanline y of a transparent 256x256 canvas.

    Stock helmet PMP files have an extra single 0xaf footer; Cleveland's
    original offic1..3 sprites have one trailing byte equal to header[3]
    (0xb7, 0xb6, 0xb4). In the observed stock helmet, 0xaf also equals
    header[3]. Some tree scenery files end after the last four-byte record.
    Accept the header-matching footer and legacy 0xaf, but reject unrelated
    single-byte tails. Framing follows record alignment, not fixed extents.
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
    # RGBA cropped to nontransparent spans; original 256x256 canvas bounds
    # are preserved. The GPU placement pivot is source pixel (128,127), not
    # the crop's midpoint. The decoder itself does not reposition sprites.
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
    # instead. Stock Papyrus sprites may have an optional one-byte trailer
    # matching the fourth (negative-top) extent byte. Earlier helmets used
    # 0xaf; keep accepting that historic variant for backward compatibility.
    if (len(data) - 12) % 4 == 0:
        spans_end = len(data)
    elif ((len(data) - 13) % 4 == 0 and
          data[-1] in (data[3], 0xaf)):
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
    # These four bytes are NOMINAL extents used for sprite placement, not
    # necessarily an enclosing bounding box. Helmet views may paint outside
    # the nominal rectangle by a pixel or more, whereas the four supplied
    # trees happen to match it exactly. Validate a plausible placement with
    # overlapping, in-canvas data, not a wrongly assumed tight rectangle.
    width, height, neg_left, neg_top = data[:4]
    left = (-neg_left) & 0xff
    top = (-neg_top) & 0xff
    right = left + (width or 256)
    bottom = top + (height or 256)
    if (right > 256 or bottom > 256 or
            not (left < max_x and min_x < right and
                 top <= max_y and min_y < bottom)):
        raise PMPError(
            f'{path.name}: implausible PMP extent header for color spans '
            f'(header {data[:4].hex()}, visible '
            f'({min_x},{min_y},{max_x},{max_y+1}))')

    rgba = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
    pix = rgba.load()
    for y, x0, x1, color in spans:
        rgb = tuple(palette[color])
        for x in range(x0, x1):
            pix[x, y] = rgb + (255,)
    bounds = (min_x, min_y, max_x, max_y + 1)
    return PMPSprite(path, rgba.crop(bounds), bounds, auxiliary)
