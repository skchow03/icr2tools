"""Read Papyrus ICR2 individual-car .3do appearance wrappers.

These are NOT geometry files. Example ind96.3do has a root MATERIAL
record referring to a RECOLOR list and an external indycar geometry name.
Every offset is relative to the 3DO body (following the filename table).
No source 3DO is ever modified by this decoder.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import struct

class AppearanceError(ValueError):
    pass

@dataclass(frozen=True)
class CarAppearance:
    path: Path
    geometry_name: str
    texture_name: str
    mapping: dict[int,int]
    source_color: int
    raw: bytes

    def map_color(self, index: int) -> int:
        return self.mapping.get(index, index)

    @property
    def description(self):
        return (f'{self.path.name}: {len(self.mapping)} RECOLOR slots, '
                f'MIP {self.texture_name or "none"}, geometry {self.geometry_name or "unspecified"}')


def _name(b):
    return b.split(b'\x00', 1)[0].decode('ascii', 'replace').strip()


def read_car_appearance(path: str | Path) -> CarAppearance:
    """Require root MATERIAL whose child is RECOLOR; reject ordinary 3DOs.

    A RECOLOR node can be at body offset 0; unlike ordinary pointer fields,
    the root MATERIAL's child offset zero is a VALID record pointer.
    """
    path=Path(path)
    raw=path.read_bytes()
    if len(raw)<20:raise AppearanceError('3DO header truncated')
    body_size,root,nm,np,no=struct.unpack_from('<5i',raw)
    if any(v<0 for v in (body_size,nm,np,no)) or nm+np+no>10000:
        raise AppearanceError('Invalid 3DO header counts')
    head=20+8*(nm+np+no)
    if head>len(raw) or len(raw)-head!=body_size:
        raise AppearanceError('3DO body size or filename table is invalid')
    data=raw[head:]
    if root<0 or root+16>len(data):raise AppearanceError('Invalid 3DO root')
    tag,mip_index,color,child=struct.unpack_from('<Iiii',data,root)
    if tag != 0x80000004:
        raise AppearanceError('Not an individual car wrapper: root is not MATERIAL')
    if child<0 or child+8>len(data):
        raise AppearanceError('MATERIAL has invalid child pointer')
    tag,count=struct.unpack_from('<Ii',data,child)
    if tag!=0x8000000e:
        raise AppearanceError('Not an individual car wrapper: MATERIAL does not reference RECOLOR')
    if count<0 or count>4096 or child+8+count*8>len(data):
        raise AppearanceError('RECOLOR table is truncated or has invalid count')
    mapping={}
    for i in range(count):
        old,new=struct.unpack_from('<ii',data,child+8+8*i)
        if not (0<=old<=255 and 0<=new<=255):
            raise AppearanceError(f'Invalid RECOLOR pair #{i+1}: {old} → {new}; palette indexes must be 0..255')
        if old in mapping:raise AppearanceError(f'Duplicate RECOLOR source index {old}')
        mapping[old]=new
    mip_names=[_name(raw[20+i*8:28+i*8]) for i in range(nm)]
    base=nm+np
    obj_names=[_name(raw[20+(base+i)*8:28+(base+i)*8]) for i in range(no)]
    texture_name=mip_names[mip_index] if 0<=mip_index<len(mip_names) else ''
    # Individual car wrappers normally have one external geometry reference.
    geometry_name=obj_names[0] if obj_names else ''
    return CarAppearance(path,geometry_name,texture_name,mapping,color,raw)


def locate_base_geometry(appearance: CarAppearance, extra_dirs=()):
    """Look for a sibling named by the appearance's external geometry ref."""
    if not appearance.geometry_name:
        return None
    wanted=appearance.geometry_name.casefold()+'.3do'
    for d in [appearance.path.parent,*extra_dirs]:
        d=Path(d)
        if not d.is_dir():continue
        direct=d/(appearance.geometry_name+'.3do')
        if direct.is_file():return direct
        for p in d.iterdir():
            if p.is_file() and p.name.casefold()==wanted:return p
    return None
