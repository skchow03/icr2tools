"""Read-only ICR2 PMP sprite decoding for 3DO PMP/PMP2 nodes.

Observed ICR2 format (stock helmet sprites):
    4-byte marker 4c38aaaf, uint32 payload byte size, uint32 auxiliary,
    followed by (y, x_start, x_end, palette_index) byte records and a single
    final af terminator. Each record fills [x_start, x_end) at scanline y.
There is no transparency palette index; absent spans are transparent.
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
    if len(data)<13 or data[:4]!=b'\x4c\x38\xaa\xaf':
        raise PMPError(f'{path.name}: PMP signature not recognized')
    declared,auxiliary=struct.unpack_from('<II',data,4)
    # Stock helmet files encode file size excluding first 12 header bytes.
    if declared not in (len(data)-12,len(data)-4,len(data)):
        raise PMPError(f'{path.name}: PMP size {declared} does not match {len(data)} bytes')
    if data[-1]!=0xaf or (len(data)-13)%4:
        raise PMPError(f'{path.name}: malformed PMP color-span records')
    if len(palette)!=256:raise PMPError('PMP requires 256 RGB palette colors')
    rgba=Image.new('RGBA',(256,256),(0,0,0,0))
    pix=rgba.load()
    for k in range(12,len(data)-1,4):
        y,x0,x1,color=data[k:k+4]
        if x1<x0:raise PMPError(f'{path.name}: inverted color span at {k}')
        c=tuple(palette[color])+(255,)
        for x in range(x0,x1):pix[x,y]=c
    bounds=rgba.getbbox()
    if bounds is None:raise PMPError(f'{path.name}: no visible spans')
    return PMPSprite(path,rgba.crop(bounds),bounds,auxiliary)
