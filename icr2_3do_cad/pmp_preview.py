"""Read-only ICR2 PMP sprite decoding for 3DO PMP/PMP2 nodes.

Two observed, structurally distinct span formats:
* Helmet PMP: 4c38aaaf marker, a series of four-byte (y, x0, x1,
  palette_index) spans, followed by one 0xaf terminator byte.
* Scenery PMP (e.g. tree2.pmp): 5b7baffb marker, four-byte spans extending
  to EOF, with NO terminator. The last span is ordinary image data.

Both contain a little-endian uint32 declared size at +4 and an auxiliary
uint32 at +8. Each span paints [x0, x1) on scanline y of a transparent
256x256 canvas. Missing spans are transparent, not a palette color key.
Do not infer the layout solely from file length: the known signature must
match the expected span framing.
"""
from pathlib import Path
from dataclasses import dataclass
import struct

class PMPError(ValueError):pass

@dataclass(frozen=True)
class PMPSprite:
    path:Path
    # RGBA cropped to nontransparent spans; pixel anchor 128,128 in source canvas
    rgba:object
    bounds:tuple[int,int,int,int]
    auxiliary:int


def load_pmp(path,palette):
    from PIL import Image
    path=Path(path)
    data=path.read_bytes()
    # A second, observed scenery variant has a distinct marker and omits
    # the helmet format's one-byte 0xaf footer. It is not compressed: the
    # final four bytes are a normal palette-index span.
    HELMET_MARKER = b'\x4c\x38\xaa\xaf'
    SCENERY_MARKER = b'\x5b\x7b\xaf\xfb'
    if len(data)<12:
        raise PMPError(f'{path.name}: PMP signature not recognized')
    signature=data[:4]
    if signature==HELMET_MARKER:
        if len(data)<17 or data[-1]!=0xaf or (len(data)-13)%4:
            raise PMPError(f'{path.name}: malformed PMP color-span records')
        spans_end=len(data)-1
    elif signature==SCENERY_MARKER:
        if len(data)<16 or (len(data)-12)%4:
            raise PMPError(f'{path.name}: malformed PMP color-span records')
        spans_end=len(data)
    else:
        raise PMPError(f'{path.name}: PMP signature not recognized')
    declared,auxiliary=struct.unpack_from('<II',data,4)
    # Stock helmets and the observed tree2 scenery both use len(data)-12;
    # retain the legacy size alternatives for previously supported PMP files.
    if declared not in (len(data)-12,len(data)-4,len(data)):
        raise PMPError(f'{path.name}: PMP size {declared} does not match {len(data)} bytes')
    if len(palette)!=256:raise PMPError('PMP requires 256 RGB palette colors')
    rgba=Image.new('RGBA',(256,256),(0,0,0,0))
    pix=rgba.load()
    for k in range(12,spans_end,4):
        y,x0,x1,color=data[k:k+4]
        if x1<x0:raise PMPError(f'{path.name}: inverted color span at {k}')
        c=tuple(palette[color])+(255,)
        for x in range(x0,x1):pix[x,y]=c
    bounds=rgba.getbbox()
    if bounds is None:raise PMPError(f'{path.name}: no visible spans')
    return PMPSprite(path,rgba.crop(bounds),bounds,auxiliary)
