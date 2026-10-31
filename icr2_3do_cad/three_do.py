"""Lossless, structure-preserving editor for Papyrus ICR2 3DO models.

Format identification and record offsets informed by skchow03/3do23d.
Also supports append-and-repoint polygon splitting without rebuilding BSP trees.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from collections import defaultdict, deque
from pathlib import Path
from typing import Iterable
import math
import struct

NAMES = {
    0: "NIL", 1: "POLY", 2: "POLY [T]", 3: "PMP", 4: "MATERIAL",
    5: "FACE", 6: "FACE2", 7: "BSPF", 8: "BSPA", 9: "BSP2",
    10: "BSPN", 11: "LIST", 12: "DYNO", 13: "RES", 14: "RECOLOR",
    15: "DYNAMIC", 16: "SUPEROBJ", 17: "DATA", 18: "PMP2",
}
MAX_NODE_COUNT = 1_000_000
MAX_LIST_COUNT = 250_000
INT32_LO, INT32_HI = -(1 << 31), (1 << 31) - 1
INT64_LO, INT64_HI = -(1 << 63), (1 << 63) - 1


class FormatError(ValueError):
    pass


@dataclass
class Vertex:
    offset: int   # Offset from start of 3DO body, NOT absolute file offset
    original: tuple[int, int, int]
    xyz: tuple[int, int, int]
    textured: bool = False
    uv: tuple[int, int] | None = None
    original_uv: tuple[int, int] | None = None

    @property
    def modified(self):
        return self.original != self.xyz

    @property
    def uv_modified(self):
        return self.uv != self.original_uv


@dataclass(frozen=True)
class PMPSpritePlacement:
    offset:int
    vertex_ref:int
    size:int
    name:str
    kind:int


@dataclass
class DynamicPlacement:
    """Placement stored in a parent 3DO; external geometry is read-only."""
    offset: int
    name: str
    file_index: int
    original_xyz: tuple[int,int,int]
    xyz: tuple[int,int,int]
    original_angles: tuple[int,int,int]  # Papyrus z, y, x signed full-turn angles
    angles: tuple[int,int,int]

    @property
    def modified(self):
        return self.xyz != self.original_xyz or self.angles != self.original_angles


@dataclass
class Polygon:
    offset: int
    kind: int
    refs: tuple[int, ...]
    color: int
    group: int = 0
    original_color: int | None = None

    def __post_init__(self):
        if self.original_color is None:
            self.original_color = self.color

    @property
    def color_modified(self):
        return self.color != self.original_color

    @property
    def unique_refs(self):
        return tuple(dict.fromkeys(self.refs))


@dataclass
class Plane:
    offset: int
    kind: int
    equation: tuple[int, int, int, int]
    # Original-plane coplanar polygons: informational, some are unrelated
    candidates: list[int] = field(default_factory=list)
    # For safe updates select only the closest descendant polygon of this plane
    anchor: int | None = None
    distance: int | None = None
    confidence: str = "unmatched"


@dataclass(frozen=True)
class PlaneEdit:
    """Explicit, per-plane user instruction; never changes the BSP tree.

    mode='original': negate/unnegate original stored coefficients.
    mode='auto': best noncollinear triplet on polygon, original orientation.
    mode='manual': cross product of three ORDERED polygon vertex refs.
    flip: invert all FOUR equation coefficients, including D.
    """
    polygon: int
    mode: str = 'auto'
    refs: tuple[int, int, int] | None = None
    flip: bool = False


@dataclass
class DistanceSwitch:
    offset: int
    anchor: int
    branches: tuple[tuple[int, int], ...]  # (minimum distance, record pointer)

    def choose(self, distance: float) -> tuple[int, int] | None:
        # Papyrus syntax lists descending distance thresholds. First matching
        # distance wins, with the 0 branch commonly used as near fallback.
        for threshold, pointer in self.branches:
            if distance >= threshold:
                return threshold, pointer
        return self.branches[-1] if self.branches else None


@dataclass
class PatchReport:
    updated_vertices: int = 0
    updated_uv: int = 0
    updated_polygon_colors: int = 0
    updated_planes: int = 0
    explicit_planes: int = 0
    untouched_planes: int = 0
    updated_dynamics: int = 0
    split_operations: int = 0
    added_polygons: int = 0
    added_vertices: int = 0
    neighbor_polygons_replaced: int = 0
    warnings: list[str] = field(default_factory=list)

    def describe(self):
        lines = [f"Vertex records changed: {self.updated_vertices}",
                 f"Texture UV records changed: {self.updated_uv}",
                 f"Polygon color records changed: {self.updated_polygon_colors}",
                 f"FACE/BSP planes rebuilt: {self.updated_planes}",
                 f"Explicit polygon plane edits: {self.explicit_planes}",
                 f"Other FACE/BSP planes unchanged: {self.untouched_planes}",
                 f"DYNAMIC transforms changed: {self.updated_dynamics}",
                 f"Topology splits: {self.split_operations}",
                 f"New active polygons: {self.added_polygons}",
                 f"New vertex records: {self.added_vertices}",
                 f"Adjacent polygon replacements: {self.neighbor_polygons_replaced}"]
        if self.warnings:
            lines += ["", "Warnings:"] + [f"- {x}" for x in self.warnings]
        return "\n".join(lines)


def i32(data: bytes | bytearray, offset: int):
    if offset < 0 or offset + 4 > len(data):
        raise FormatError(f"Read beyond body at {offset}")
    return struct.unpack_from("<i", data, offset)[0]


def i64(data: bytes | bytearray, offset: int):
    if offset < 0 or offset + 8 > len(data):
        raise FormatError(f"Read beyond body at {offset}")
    return struct.unpack_from("<q", data, offset)[0]


def cross(u, v):
    return (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])


def sub(u, v):
    return tuple(a-b for a, b in zip(u, v))


def dot(u, v):
    return sum(a*b for a, b in zip(u, v))


def plane_distance(eq, point):
    a,b,c,d = eq
    n = math.hypot(a,b,c)
    return abs((a*point[0]+b*point[1]+c*point[2]+d) / n) if n else math.inf


def polygon_triplet(poly: Polygon, vertices: dict[int, Vertex], *, original=False):
    coords = [(vertices[r].original if original else vertices[r].xyz, r)
              for r in poly.unique_refs if r in vertices]
    if len(coords) < 3:
        return None
    # Prefer well-separated points so the new plane is numerically stable.
    best = None
    max_a = 0
    for ia in range(len(coords)-2):
        for ib in range(ia+1, len(coords)-1):
            for ic in range(ib+1, len(coords)):
                p, q, r = coords[ia][0], coords[ib][0], coords[ic][0]
                normal = cross(sub(q,p), sub(r,p))
                area2 = dot(normal, normal)
                if area2 > max_a:
                    best, max_a = (p,q,r), area2
    return best


def polygon_triplet_refs(poly: Polygon, vertices: dict[int, Vertex]):
    """Three polygon vertex body offsets forming the largest triangle."""
    refs=[r for r in poly.unique_refs if r in vertices]
    best=None;area=0
    for i in range(len(refs)-2):
        for j in range(i+1,len(refs)-1):
            for k in range(j+1,len(refs)):
                p,q,r=[vertices[refs[idx]].xyz for idx in (i,j,k)]
                norm=cross(sub(q,p),sub(r,p))
                a=dot(norm,norm)
                if a>area:
                    best,area=(refs[i],refs[j],refs[k]),a
    return best


def equation_from_polygon(poly: Polygon, vertices: dict[int, Vertex],
                          old_eq: tuple[int, int, int, int]):
    tri = polygon_triplet(poly, vertices)
    if tri is None:
        raise FormatError(f"Polygon at {poly.offset} is degenerate (no plane)")
    p0,p1,p2 = tri
    a,b,c = cross(sub(p1,p0),sub(p2,p0))
    old_normal = old_eq[:3]
    if dot((a,b,c),old_normal) < 0:
        a,b,c = -a,-b,-c
    max_new = max(abs(a),abs(b),abs(c))
    max_old = max(abs(k) for k in old_normal)
    if max_new == 0 or max_old == 0:
        raise FormatError("Plane has zero normal")
    # Preserve the original coefficient magnitude. Changing this by orders
    # of magnitude can change fixed-point/arithmetic behavior in the game.
    # Avoid floating point: integer rounded ratios.
    def div_round(n, den):
        return (n + den//2)//den if n >= 0 else -((-n+den//2)//den)
    aa,bb,cc = (div_round(k*max_old,max_new) for k in (a,b,c))
    if (aa,bb,cc) == (0,0,0):
        raise FormatError("Rebuilt normal rounds to zero")
    dd = -dot((aa,bb,cc),p0)
    while (not all(INT32_LO <= v <= INT32_HI for v in (aa,bb,cc))
           or not INT64_LO <= dd <= INT64_HI):
        aa,bb,cc = (div_round(k,2) for k in (aa,bb,cc))
        dd = -dot((aa,bb,cc),p0)
        if (aa,bb,cc)==(0,0,0):
            raise FormatError("Plane cannot be represented")
    return aa,bb,cc,dd


def equation_from_triplet(points, old_eq, *, preserve_facing=False):
    """Produce a 3DO-compatible integer plane from three ordered vertices.

    Scale to the original normal's largest coefficient to avoid arbitrary
    magnitude changes. The order of the three refs determines the sign
    unless preserve_facing=True. D is computed after scaling.
    """
    if len(points) != 3:
        raise FormatError('A plane needs exactly three vertices')
    p0,p1,p2=points
    normal=cross(sub(p1,p0),sub(p2,p0))
    if normal==(0,0,0):
        raise FormatError('Selected vertices are collinear; choose a different triplet')
    if preserve_facing and dot(normal,old_eq[:3])<0:
        normal=tuple(-v for v in normal)
    amplitude=max(abs(n) for n in old_eq[:3])
    if amplitude==0:
        raise FormatError('Original BSP plane has a zero normal')
    maxnorm=max(abs(n) for n in normal)
    def rounded(n,d):
        return (n+d//2)//d if n>=0 else -((-n+d//2)//d)
    abc=tuple(rounded(a*amplitude,maxnorm) for a in normal)
    if abc==(0,0,0):
        raise FormatError('Plane normal rounds to zero')
    d=-dot(abc,p0)
    while (any(not INT32_LO <= v <= INT32_HI for v in abc)
           or not INT64_LO <= d <= INT64_HI):
        abc=tuple(rounded(k,2) for k in abc)
        if abc==(0,0,0):
            raise FormatError('Computed normal overflows 3DO limits')
        d=-dot(abc,p0)
    return (*abc,d)


class Model:
    def __init__(self, path: str | Path, *, raw_data: bytes | None = None, topology_history=()):
        self.path = Path(path)
        self.raw = self.path.read_bytes() if raw_data is None else bytes(raw_data)
        self.topology_history = tuple(topology_history)
        if len(self.raw) < 20:
            raise FormatError("3DO header is truncated")
        body_size, self.root_offset, nmip, npmp, nobj = struct.unpack_from("<5i",self.raw)
        if min(nmip,npmp,nobj,body_size) < 0 or (nmip+npmp+nobj) > 100000:
            raise FormatError("3DO header has implausible counts")
        self.body_start = 20+8*(nmip+npmp+nobj)
        if self.body_start > len(self.raw):
            raise FormatError("3DO filename table is truncated")
        self.body = self.raw[self.body_start:]
        if body_size != len(self.body):
            raise FormatError(f"3DO body_size={body_size} but found {len(self.body)} bytes")
        self.polygons: dict[int, Polygon] = {}
        self.planes: dict[int, Plane] = {}
        self.switches: dict[int, DistanceSwitch] = {}
        self.lod_anchors: set[int] = set()
        self.vertices: dict[int, Vertex] = {}
        self.records: dict[int,int] = {}
        self.children: dict[int, list[int]] = {}
        self.warnings: list[str] = []
        self.plane_edits: dict[int, PlaneEdit] = {}
        self._ancestor_plane_cache: dict[int, tuple[int, ...]] = {}
        self.pmp_names = [
            self.raw[20+8*nmip+8*i:20+8*nmip+8*(i+1)].split(b"\x00")[0].decode("ascii","replace").strip()
            for i in range(npmp)]
        self.pmp_sprites: dict[int,PMPSpritePlacement] = {}
        self.mip_names = [self.raw[20+i*8:28+i*8].split(b'\x00')[0].decode('ascii','replace').strip() for i in range(nmip)]
        self.materials: dict[int,tuple[str,int]] = {}
        self.polygon_materials: dict[int,str] = {}
        self.nested_3dos = nobj
        extern_start = 20 + 8 * (nmip + npmp)
        self.external_names = [
            self.raw[extern_start+8*i:extern_start+8*(i+1)].split(b"\x00")[0].decode("ascii", "replace").strip()
            for i in range(nobj)
        ]
        self.dynamics: dict[int, DynamicPlacement] = {}
        # Negative pointers are external 3DO references, indexed from -1.
        self._parse()
        self._associate_planes()

    def _parse(self):
        pending = [self.root_offset]
        vertex_types: dict[int, bool] = {}
        while pending:
            off=pending.pop()
            if off in self.records:
                continue
            if len(self.records)>MAX_NODE_COUNT:
                raise FormatError("3DO exceeds safe node limit")
            tag=i32(self.body,off)
            if tag == 0:
                kind=0
            elif tag < 0 and (tag & 0x7fffffff) in NAMES and (tag & 0xffffffff)>>24==128:
                kind=tag & 0x7fffffff
            else:
                raise FormatError(f"Unknown flavor {tag & 0xffffffff:08x} at body offset {off}")
            child=[]
            if kind in (1,2):
                textured=(kind==2)
                count=i32(self.body, off+(12 if textured else 8))+1
                base=off+(16 if textured else 12)
                if not 1<=count<=MAX_LIST_COUNT or base+count*4>len(self.body):
                    raise FormatError(f"Invalid polygon vertex count at {off}")
                refs=tuple(i32(self.body, base+j*4) for j in range(count))
                for ref in refs:
                    vertex_types[ref]=vertex_types.get(ref,False) or textured
                self.polygons[off] = Polygon(off,kind,refs, i32(self.body,off+(8 if textured else 4)),
                                              i32(self.body,off+4) if textured else 0)
            elif 5<=kind<=10:
                equation=tuple(i32(self.body,off+k) for k in (4,8,12))+(i64(self.body,off+16),)
                self.planes[off]=Plane(off,kind,equation)
                offsets={5:(24,),6:(24,28),7:(24,28,32),8:(24,28,32),
                         9:(24,28,32,36),10:(24,28)}[kind]
                child = [i32(self.body,off+k) for k in offsets]
            elif kind==11:
                count=i32(self.body,off+4)
                if not 0<=count<=MAX_LIST_COUNT or off+8+count*4>len(self.body):
                    raise FormatError(f"Invalid LIST count at {off}")
                child=[i32(self.body,off+8+4*j) for j in range(count)]
            elif kind==13:
                anchor=i32(self.body,off+4)
                # SWITCH DISTANCE (RES) is VARIABLE LENGTH. The first
                # zero threshold terminates the list with its fallback
                # child. Real wheel 3DOs use only three branches, with
                # the record sitting at the very end of the file.
                branches=[]
                for threshold_off in (8,16,24,32):
                    if off+threshold_off+8>len(self.body):
                        raise FormatError(f'Truncated SWITCH DISTANCE at {off}')
                    threshold=i32(self.body,off+threshold_off)
                    pointer=i32(self.body,off+threshold_off+4)
                    branches.append((threshold,pointer))
                    if threshold==0:
                        break
                pairs=tuple(branches)
                self.switches[off]=DistanceSwitch(off,anchor,pairs)
                self.lod_anchors.add(anchor)
                child=[ptr for threshold,ptr in pairs]
            elif kind==15:
                xyz = tuple(i32(self.body, off+j) for j in (4,8,12))
                angles = tuple(i32(self.body, off+j) for j in (16,20,24))
                index = -i32(self.body,off+28)
                if not 1 <= index <= len(self.external_names):
                    self.warnings.append(f"DYNAMIC @{off}: invalid external file index {-index}")
                    name=f"(invalid external index {index})"
                else:
                    name=self.external_names[index-1]
                self.dynamics[off]=DynamicPlacement(off,name,index,xyz,xyz,angles,angles)
            elif kind==16:
                count=i32(self.body,off+8)
                if not 0<=count<=MAX_LIST_COUNT or off+12+count*4>len(self.body):
                    raise FormatError(f"Invalid SUPEROBJ count at {off}")
                child=[i32(self.body,off+4)]+[i32(self.body,off+12+4*j) for j in range(count)]
            elif kind==4:
                mip_number=i32(self.body,off+4)
                if 0<=mip_number<len(self.mip_names):
                    self.materials[off]=(self.mip_names[mip_number],i32(self.body,off+12))
                else:
                    self.warnings.append(f'MATERIAL @{off} invalid MIP index {mip_number}')
                child=[i32(self.body,off+12)]
            elif kind in (3,18):
                vertex_ref=i32(self.body,off+4)
                vertex_types[vertex_ref] = False
                name_index=i32(self.body,off+12)
                if 0<=name_index<len(self.pmp_names):
                    self.pmp_sprites[off]=PMPSpritePlacement(
                        off,vertex_ref,i32(self.body,off+8),self.pmp_names[name_index],kind)
                else:
                    self.warnings.append(f'PMP/PMP2 @{off}: invalid PMP name index {name_index}')
            # Zero child is conventionally a NIL / null pointer. It is safe
            # to skip; zero-valued vertices (if referenced) are handled below.
            child=[p for p in child if p != 0]
            for p in child:
                if p < 0:
                    if -p > len(self.external_names):
                        raise FormatError(f"Invalid external 3DO pointer {p} at {off}")
                elif p >=len(self.body):
                    raise FormatError(f"Out-of-range child pointer {p} at {off}")
            self.children[off]=child
            self.records[off]=kind
            # Negative pointers resolve to a named external 3DO, not a
            # local record. Do not try to parse them from this body.
            pending.extend(p for p in child if p>0)
        for anchor in self.lod_anchors:
            # The SWITCH reference point can be distinct from vertices used
            # in any visible polygon. It is still a real editable coordinate.
            vertex_types.setdefault(anchor,False)
        for off, textured in sorted(vertex_types.items()):
            if off < 0 or off+(20 if textured else 16)>len(self.body):
                raise FormatError(f"Out-of-range vertex pointer {off}")
            coords=tuple(i32(self.body,off+j) for j in (4,8,12))
            uv=struct.unpack_from('<HH',self.body,off+16) if textured else None
            self.vertices[off]=Vertex(off,coords,coords,textured,uv,uv)
        for material_offset, (name, child_offset) in self.materials.items():
            # A material applies to all descendant POLY[T] records, including
            # nested LIST/BSP children, without rewriting source record order.
            pending_material=[child_offset]; seen_material=set()
            while pending_material:
                current=pending_material.pop()
                if current in seen_material:continue
                seen_material.add(current)
                if current in self.polygons and self.polygons[current].kind==2:
                    self.polygon_materials.setdefault(current,name)
                pending_material.extend(self.children.get(current,[]))
        if not self.vertices:
            self.warnings.append("No editable geometry: file may be an object placement / material wrapper")

    def _descendant_poly_distances(self, node: int):
        queue=deque((p,1) for p in self.children.get(node,[]))
        seen={node}; distances={}
        while queue:
            item,depth=queue.popleft()
            if item in seen:
                continue
            seen.add(item)
            if item in self.polygons:
                distances[item]=depth
            for child in self.children.get(item,[]):
                queue.append((child,depth+1))
        return distances

    def _associate_planes(self):
        # Coplanarity checked against the UNEDITED source. A global plane
        # resemblance is NOT sufficient: only descendant surface polygons
        # count as eligible auto-rebuild anchors.
        for pl in self.planes.values():
            a,b,c,d=pl.equation
            if (a,b,c)==(0,0,0):
                continue
            candidates=[]
            for poly in self.polygons.values():
                if len(poly.unique_refs)<3:
                    continue
                if polygon_triplet(poly,self.vertices,original=True) is None:
                    continue
                pts=[self.vertices[r].original for r in poly.unique_refs]
                if all(plane_distance(pl.equation, p)<=0.5 for p in pts):
                    candidates.append(poly.offset)
            pl.candidates=candidates
            local=self._descendant_poly_distances(pl.offset)
            eligible=[p for p in candidates if p in local]
            if not eligible:
                pl.confidence = "global-only" if candidates else "unmatched"
                continue
            eligible.sort(key=lambda p: (local[p],p))
            pl.anchor=eligible[0]
            pl.distance=local[pl.anchor]
            nearest=[p for p in eligible if local[p]==pl.distance]
            pl.confidence="local" if len(nearest)==1 else "ambiguous"
            # Only a unique closest descendant is regarded as safe to rebuild.
            if len(nearest)>1:
                pl.anchor=None

    def planes_for_polygon(self, polygon_offset: int):
        """All ancestor FACE/BSP records that structurally contain this POLY.

        Ordered: anchored-to-poly first, then coplanar ancestors, then
        unrelated partition planes (shown for explicit advanced editing).
        """
        if polygon_offset not in self.polygons:
            raise KeyError(polygon_offset)
        if polygon_offset not in self._ancestor_plane_cache:
            related=[]
            for pl in self.planes.values():
                if polygon_offset in self._descendant_poly_distances(pl.offset):
                    related.append(pl.offset)
            related.sort(key=lambda off: (
                0 if self.planes[off].anchor==polygon_offset else
                1 if polygon_offset in self.planes[off].candidates else 2,
                self._descendant_poly_distances(off).get(polygon_offset,999999),off))
            self._ancestor_plane_cache[polygon_offset]=tuple(related)
        return self._ancestor_plane_cache[polygon_offset]

    def plane_relationship(self, polygon_offset, plane_offset):
        if plane_offset not in self.planes_for_polygon(polygon_offset):
            return 'not an ancestor of this polygon'
        p=self.planes[plane_offset]
        if p.anchor==polygon_offset:
            return 'unique local surface match'
        if polygon_offset in p.candidates:
            return 'coplanar ancestor / shared partition'
        return 'ancestor partition; not coplanar in source'

    def _check_plane_target(self, plane_offset, polygon_offset):
        if polygon_offset not in self.polygons:
            raise ValueError('Select a valid polygon')
        if plane_offset not in self.planes_for_polygon(polygon_offset):
            raise ValueError('Plane is not an ancestor of the selected polygon')

    def set_plane_edit(self, plane_offset: int, polygon_offset: int,
                       mode: str, refs: tuple[int, int, int] | None = None,
                       *, flip: bool = False):
        self._check_plane_target(plane_offset,polygon_offset)
        if mode not in ('original','auto','manual'):
            raise ValueError('Plane edit mode must be original, auto or manual')
        poly=self.polygons[polygon_offset]
        if mode=='original':
            if refs is not None:
                raise ValueError('Original mode cannot specify vertex references')
            if not flip:
                self.plane_edits.pop(plane_offset,None)
                return
        elif polygon_triplet(poly,self.vertices) is None:
            raise ValueError('Polygon has no noncollinear vertex triplet')
        if mode=='manual':
            if refs is None or len(refs)!=3 or len(set(refs))!=3:
                raise ValueError('Select three distinct vertices in an ordered triplet')
            if any(r not in poly.unique_refs for r in refs):
                raise ValueError('Manual plane vertices must belong to the selected polygon')
        elif refs is not None:
            raise ValueError('Vertex references are only used in manual mode')
        prospective=PlaneEdit(polygon_offset,mode,tuple(refs) if refs is not None else None,flip)
        self._equation_for_edit(plane_offset,prospective)  # validate before recording
        self.plane_edits[plane_offset]=prospective

    def _equation_for_edit(self, plane_offset: int, edit: PlaneEdit):
        pl=self.planes[plane_offset]
        poly=self.polygons[edit.polygon]
        if edit.mode=='original':
            equation=pl.equation
        elif edit.mode=='auto':
            equation=equation_from_polygon(poly,self.vertices,pl.equation)
        elif edit.mode=='manual':
            points=[self.vertices[r].xyz for r in edit.refs]
            equation=equation_from_triplet(points,pl.equation,preserve_facing=False)
        else:
            raise ValueError('Unrecognized plane edit mode')
        # Explicit user-chosen planes need not contain every polygon vertex.
        # N-gons in real 3DOs can be approximately planar (or deliberately
        # use a splitting plane). Only a zero/invalid normal is rejected by
        # equation_from_polygon/equation_from_triplet. Implicit safe rebuilds
        # still perform their strict coplanarity check in build_modified_bytes.
        if edit.flip:
            equation=tuple(-v for v in equation)
        if any(not INT32_LO<=v<=INT32_HI for v in equation[:3]) or not INT64_LO<=equation[3]<=INT64_HI:
            raise FormatError('Inverted plane coefficients overflow signed 3DO field')
        return equation

    def polygon_plane_deviation(self, polygon_offset: int, equation):
        """Max perpendicular distance and fraction of bbox diagonal (raw units).

        Diagnostic only: this deliberately DOES NOT limit explicit plane edits.
        """
        poly=self.polygons[polygon_offset]
        pts=[self.vertices[r].xyz for r in poly.unique_refs]
        if not pts:
            return 0.0, 0.0
        maximum=max(plane_distance(equation,xyz) for xyz in pts)
        span=math.sqrt(sum((max(xyz[axis] for xyz in pts)-min(xyz[axis] for xyz in pts))**2
                           for axis in range(3)))
        return maximum, (maximum/span if span else 0.0)

    def effective_plane(self, plane_offset):
        if plane_offset not in self.planes:
            raise KeyError(plane_offset)
        if plane_offset in self.plane_edits:
            return self._equation_for_edit(plane_offset,self.plane_edits[plane_offset])
        # Same fallback as preview, but no file mutation
        data,_=self.build_modified_bytes()
        return struct.unpack_from('<3iq',data,self.body_start+plane_offset+4)

    def flip_plane(self, plane_offset, polygon_offset):
        self._check_plane_target(plane_offset,polygon_offset)
        existing=self.plane_edits.get(plane_offset)
        if existing is None:
            self.set_plane_edit(plane_offset,polygon_offset,'original',flip=True)
        else:
            new=replace(existing,flip=not existing.flip)
            if new.mode=='original' and not new.flip:
                self.plane_edits.pop(plane_offset,None)
            else:
                self._equation_for_edit(plane_offset,new)
                self.plane_edits[plane_offset]=new

    def restore_plane_edit(self, plane_offset, state: PlaneEdit | None):
        if state is None:
            self.plane_edits.pop(plane_offset,None)
        else:
            self.set_plane_edit(plane_offset,state.polygon,state.mode,state.refs,flip=state.flip)

    def get_vertex(self, offset):
        return self.vertices[offset]

    def set_vertex(self, offset: int, xyz: Iterable[int]):
        if offset not in self.vertices:
            raise KeyError(f"Unknown vertex {offset}")
        vals=tuple(int(x) for x in xyz)
        if len(vals)!=3 or any(v<INT32_LO or v>INT32_HI for v in vals):
            raise ValueError("Coordinates must be three signed 32-bit integers")
        self.vertices[offset].xyz=vals

    def set_polygon_color(self, offset: int, color: int):
        """Change a POLY's own 8-bit palette index; do not alter RECOLOR wrappers."""
        if offset not in self.polygons:
            raise KeyError(f'Unknown polygon {offset}')
        value = int(color)
        if not 0 <= value <= 255:
            raise ValueError('Polygon palette index must be an integer from 0 through 255')
        self.polygons[offset].color = value

    def face2_pair(self, offset: int) -> int | None:
        """Return the other polygon face only for a direct FACE2 two-face node."""
        if offset not in self.polygons:
            return None
        for parent,kind in self.records.items():
            if kind != 6:
                continue
            members = self.children.get(parent,())
            if len(members) == 2 and offset in members:
                other = members[1] if members[0] == offset else members[0]
                if other in self.polygons:
                    first=self.polygons[offset];second=self.polygons[other]
                    if first.kind == second.kind and set(first.unique_refs) == set(second.unique_refs):
                        return other
        return None

    def set_uv(self, offset: int, uv: Iterable[int]):
        vertex=self.vertices[offset]
        if not vertex.textured:
            raise ValueError("This vertex has no texture UV coordinates")
        vals=tuple(int(x) for x in uv)
        if len(vals)!=2 or any(v<0 or v>65535 for v in vals):
            raise ValueError("U and V must be unsigned 16-bit integers (0..65535)")
        vertex.uv=vals

    def set_dynamic(self, offset:int, xyz=None, angles=None):
        pl=self.dynamics[offset]
        xyz=pl.xyz if xyz is None else tuple(int(v) for v in xyz)
        angles=pl.angles if angles is None else tuple(int(v) for v in angles)
        if len(xyz)!=3 or len(angles)!=3 or any(not INT32_LO<=v<=INT32_HI for v in (*xyz,*angles)):
            raise ValueError("DYNAMIC position and rotations must fit signed 32-bit integers")
        pl.xyz=xyz
        pl.angles=angles

    def split_polygon(self, polygon_offset, edge_a, edge_b, fraction_a=.5, fraction_b=.5):
        """Return (new_model, SplitResult). Original model stays untouched.

        The returned model carries the complete edited byte stream and current
        original file path, so subsequent XYZ/UV edits and saves still work.
        """
        from topology_split import split_bytes
        data, result = split_bytes(self, polygon_offset, edge_a, edge_b,
                                   fraction_a, fraction_b)
        new_model = Model(self.path, raw_data=data,
                          topology_history=(*self.topology_history, result))
        if not all(off in new_model.polygons for off in result.new_polygons):
            raise FormatError('Split output failed structural round-trip')
        # Ensure there are no accidental dangling pointers to the replaced
        # polygon anywhere reachable from the header root.
        if polygon_offset in new_model.polygons:
            raise FormatError('Original polygon remains reachable after repoint')
        return new_model, result

    def split_polygon_at_vertices(self, polygon_offset, vertex_a, vertex_b):
        """Return a new model split along existing vertex-list indices (0-based).

        Adds exactly two polygon records and one ordered LIST, without adding
        vertex records or modifying any existing BSP plane or SWITCH node.
        """
        from topology_split import split_existing_vertices_bytes
        data, result = split_existing_vertices_bytes(self, polygon_offset, vertex_a, vertex_b)
        new_model = Model(self.path, raw_data=data,
                          topology_history=(*self.topology_history, result))
        if not all(off in new_model.polygons for off in result.new_polygons):
            raise FormatError('Existing-vertex split failed structural round-trip')
        if polygon_offset in new_model.polygons:
            raise FormatError('Original polygon remains reachable after repoint')
        if result.new_vertices:
            raise FormatError('Existing-vertex split unexpectedly allocated vertices')
        return new_model, result

    def reset(self):
        self.plane_edits.clear()
        for poly in self.polygons.values():
            poly.color = poly.original_color
        for pl in self.dynamics.values():
            pl.xyz=pl.original_xyz
            pl.angles=pl.original_angles
        for v in self.vertices.values():
            v.xyz=v.original
            v.uv=v.original_uv

    @property
    def modified_vertices(self):
        return [v for v in self.vertices.values() if v.modified]

    @property
    def modified_uvs(self):
        return [v for v in self.vertices.values() if v.uv_modified]

    @property
    def modified_polygon_colors(self):
        return [poly for poly in self.polygons.values() if poly.color_modified]

    @property
    def modified_dynamics(self):
        return [pl for pl in self.dynamics.values() if pl.modified]

    @property
    def dirty(self):
        return bool(self.modified_vertices or self.modified_uvs or self.modified_polygon_colors or self.plane_edits or self.modified_dynamics or self.topology_history)

    def switched_polygons(self, distance: float | None, camera,
                          bsp_mode: str = 'off', events: list | None = None):
        """Return (visible polygon offsets, stats, selected LOD branches).

        `distance=None`: all switch branches for historical full-geometry view.
        `bsp_mode`: off, original, rebuilt. Orthographic camera on the visible
        side is approximated by a position along the view direction.
        This is an inspection tool, not a byte-identical ICR2 rasterizer.
        """
        if bsp_mode not in ('off', 'original', 'rebuilt'):
            raise ValueError(f'Invalid BSP mode {bsp_mode}')
        equations={p.offset:p.equation for p in self.planes.values()}
        if bsp_mode=='rebuilt' and (self.modified_vertices or self.plane_edits):
            data,_=self.build_modified_bytes()
            for off in equations:
                loc=self.body_start+off
                equations[off]=struct.unpack_from('<3iq',data,loc+4)
        seen=set()
        traversed=set()
        visible=[]
        lod=[]
        excluded=set()
        culled_nodes=0
        node_tests=0
        def walk(node,stack,material=None):
            nonlocal culled_nodes,node_tests
            # Offset zero is a legitimate root (e.g. 52-byte sfront/srear
            # MATERIAL wrappers). It is NIL only when reached as a child.
            if (node==0 and stack) or node in stack:
                return
            if node<0:
                if events is not None:
                    events.append(('external',node,material))
                return
            if node in self.polygons:
                if node not in seen:
                    seen.add(node); visible.append(node)
                    if events is not None: events.append(('polygon',node))
                return
            kind=self.records.get(node)
            if kind is None or node in traversed:return
            traversed.add(node)
            if kind==15:
                if events is not None: events.append(('dynamic',node))
                return
            if kind in (3,18):
                if events is not None and node in self.pmp_sprites: events.append(('pmp',node))
                return
            child=self.children.get(node,())
            if kind==4:
                # Material wrappers can point directly to an external 3DO
                # (sfront -> fwheel and srear -> rwheel). Carry the MIP name
                # across that boundary, without changing any source file.
                material=self.materials.get(node,(material,None))[0]
            if kind==13:
                sw=self.switches[node]
                if distance is None:
                    picks=[p for _,p in sw.branches]
                else:
                    chosen=sw.choose(distance)
                    if chosen:
                        lod.append((node,chosen[0],chosen[1]))
                    picks=[chosen[1]] if chosen else []
                    excluded.update(p for _,p in sw.branches if p not in picks)
                for ptr in picks:walk(ptr,stack | {node},material)
                return
            if kind in (5,6,7,8,9,10) and bsp_mode!='off':
                eq=equations[node]
                # Camera side of plane: positive is front-facing. In-plane
                # tolerance is deliberately small relative to its normal.
                val=dot(eq[:3],camera)+eq[3]
                norm=math.sqrt(dot(eq[:3],eq[:3]))
                sign=1 if val>=-norm*0.01 else -1
                node_tests+=1
                if kind==5:  # FACE: its only subtree is one-sided
                    if sign<0:
                        culled_nodes+=1
                        return
                elif kind==6:  # FACE2: separate FRONT and BACK branches
                    # Binary slots +24,+28 retain the same order as the
                    # N3 FACE2 (plane), front_object, back_object statement.
                    # Drawing both children made selected polygons look
                    # two-sided even when their back-side child differed.
                    front=i32(self.body,node+24)
                    back=i32(self.body,node+28)
                    if front and back and front!=back:
                        culled_nodes+=1
                    walk(front if sign>=0 else back, stack | {node},material)
                    return
                elif kind==7:  # BSPF: second text argument is one-sided
                    # ICR2 binary has front/near/far pointers reordered
                    # compared with the N3 textual BSPF statement.
                    # Read raw slots, including NIL, instead of the filtered
                    # list. The N3-facing center branch is binary slot 32.
                    a,b,c=(i32(self.body,node+i) for i in (24,28,32))
                    order=(b,c,a) if sign>0 else (a,b)
                    if sign<0 and c:culled_nodes+=1
                    for ptr in order:walk(ptr,stack | {node},material)
                    return
                elif kind==8:  # BSPA changes sorting, none of its 3 branches culled
                    a,b,c=(i32(self.body,node+i) for i in (24,28,32))
                    for ptr in ((b,c,a) if sign>0 else (a,c,b)):
                        walk(ptr,stack | {node},material)
                    return
                elif kind==10: # BSPN is a two-branch near/far sorter
                    a,b=(i32(self.body,node+i) for i in (24,28))
                    for ptr in ((b,a) if sign>0 else (a,b)):
                        walk(ptr,stack | {node},material)
                    return
                elif kind==9:  # BSP2: BSP splitting AND side-dependent face selection.
                    # ICR2 binary pointer layout is A,D,C,B in N3 source
                    # order (see Papyrus converter notes). The common car
                    # arrangement is [NIL, rest_of_car, textured_front,
                    # plain_back]. Drawing all four children incorrectly
                    # overlays coincident front/back surfaces and also paints
                    # the rest of the car on top of the near-side plate.
                    a,d,c,b=(i32(self.body,node+i) for i in (24,28,32,36))
                    # Paint far objects first, then the plane-facing surface,
                    # and any near objects last. The front face C is visible
                    # from the plane's positive half-space; B is the reverse
                    # face visible from the negative half-space. D is the
                    # continuing subtree and A is the far-side subtree.
                    # Keeping NIL pointers is harmless (walk skips 0).
                    order=(a,d,c) if sign>=0 else (b,d,a)
                    culled_nodes += int(bool(b if sign>=0 else c))
                    for ptr in order:
                        walk(ptr,stack | {node},material)
                    return
            if kind==11:  # LIST: painter's algorithm, authored back to front.
                # Never depth-sort this sequence in the renderer.
                for ptr in child:
                    walk(ptr,stack | {node},material)
                return
            for ptr in child:
                walk(ptr,stack | {node},material)
        walk(self.root_offset,set())
        return visible,{'visible':len(visible), 'culled_nodes':culled_nodes,
                        'tested_planes':node_tests,
                        'excluded_branches':len(excluded)},lod

    def summary(self):
        from collections import Counter
        levels=Counter(p.confidence for p in self.planes.values())
        return (f"{len(self.vertices)} vertices | {len(self.polygons)} polygons | "
                f"{len(self.planes)} FACE/BSP planes | {len(self.switches)} SWITCH DISTANCE\n"
                f"Plane associations: {levels['local']} unique local, "
                f"{levels['ambiguous']} ambiguous, "
                f"{levels['global-only']} global-only, {levels['unmatched']} unmatched")

    def build_modified_bytes(self):
        patched=bytearray(self.raw)
        report=PatchReport(updated_vertices=len(self.modified_vertices),
                           updated_uv=len(self.modified_uvs),
                           updated_polygon_colors=len(self.modified_polygon_colors),
                           split_operations=len(self.topology_history),
                           added_polygons=sum(len(r.new_polygons) for r in self.topology_history),
                           added_vertices=sum(len(r.new_vertices) for r in self.topology_history),
                           neighbor_polygons_replaced=sum(len(r.updated_neighbors) for r in self.topology_history))
        for result in self.topology_history:
            report.warnings.extend(result.warnings)
        if any(getattr(r, 'face_offset', -1) < 0 for r in self.topology_history):
            report.warnings.append('New split polygons share their previous FACE/BSP plane(s); '
                'editing the two halves into different planes may require manual BSP restructuring.')
        for poly in self.modified_polygon_colors:
            # POLY: color at +4; textured POLY [T]: group +4, color +8.
            relative=poly.offset+(8 if poly.kind==2 else 4)
            struct.pack_into('<i',patched,self.body_start+relative,poly.color)
        for pl in self.modified_dynamics:
            struct.pack_into('<6i',patched,self.body_start+pl.offset+4,*pl.xyz,*pl.angles)
            report.updated_dynamics+=1
        modified={v.offset for v in self.modified_vertices}
        for v in self.modified_uvs:
            struct.pack_into('<HH',patched,self.body_start+v.offset+16,*v.uv)
        if not modified and not self.plane_edits:
            report.untouched_planes=len(self.planes)
            return bytes(patched),report
        for v in self.modified_vertices:
            struct.pack_into('<3i',patched,self.body_start+v.offset+4,*v.xyz)
        associated=set()
        for pl in self.planes.values():
            if pl.offset in self.plane_edits:
                edit=self.plane_edits[pl.offset]
                try:
                    eq=self._equation_for_edit(pl.offset,edit)
                    # Unlike automatic association, this is a deliberate user
                    # selection. Do not silently move any other partition.
                    struct.pack_into('<3iq',patched,self.body_start+pl.offset+4,*eq)
                    report.updated_planes += 1
                    report.explicit_planes += 1
                    if edit.mode in ('manual','auto'):
                        deviation,relative=self.polygon_plane_deviation(edit.polygon,eq)
                        if deviation>1.0:
                            report.warnings.append(
                                f'{NAMES[pl.kind]} at {pl.offset}: intentionally noncoplanar '
                                f'POLY {edit.polygon}; furthest vertex {deviation:.1f} raw units '
                                f'({relative*100:.2f}% of polygon bbox diagonal) from chosen plane. '
                                'Saved as requested; test BSP visibility in-game.')
                    if self.plane_relationship(edit.polygon,pl.offset).startswith('ancestor partition'):
                        report.warnings.append(
                          f'{NAMES[pl.kind]} at {pl.offset}: deliberately overridden from polygon {edit.polygon}, '
                          'which was not coplanar with this partition in the source; verify BSP in-game')
                    affected_other=[p for p in pl.candidates if p!=edit.polygon and
                                    any(r in modified for r in self.polygons[p].unique_refs)]
                    if affected_other:
                        report.warnings.append(f'{NAMES[pl.kind]} at {pl.offset}: manual plane edit also shares '
                          f'{len(affected_other)} other originally coplanar polygons; review those surfaces')
                except (FormatError,OverflowError,ValueError,struct.error) as exc:
                    # Fail closed: never create an output where a deliberately
                    # edited plane is silently omitted.
                    raise FormatError(f'Explicit plane {pl.offset} cannot be saved: {exc}') from exc
                continue
            affected=[p for p in pl.candidates
                      if any(r in modified for r in self.polygons[p].unique_refs)]
            if not affected:
                report.untouched_planes+=1
                continue
            associated.update(r for p in affected for r in self.polygons[p].unique_refs if r in modified)
            local=self._descendant_poly_distances(pl.offset)
            if pl.confidence=='local':
                anchor=pl.anchor
            elif pl.confidence=='ambiguous':
                # Multiple immediately related surfaces occupied the same
                # plane originally. We may rebuild it only if a moved nearest
                # surface and ALL local coincident surfaces still agree on
                # a single new plane. This is checked below.
                close=[p for p in pl.candidates if p in local and local[p]==pl.distance]
                changed_close=[p for p in close if p in affected]
                anchor=changed_close[0] if changed_close else None
            else:
                anchor=None
            if anchor is None:
                report.untouched_planes+=1
                report.warnings.append(
                    f"{NAMES[pl.kind]} at {pl.offset}: edited coplanar surface, "
                    f"but plane association is {pl.confidence}; left unchanged")
                continue
            if anchor not in affected:
                report.untouched_planes+=1
                report.warnings.append(
                    f"{NAMES[pl.kind]} at {pl.offset}: a non-anchor coplanar polygon moved; "
                    f"plane unchanged")
                continue
            poly=self.polygons[anchor]
            try:
                equation=equation_from_polygon(poly,self.vertices,pl.equation)
                # Detect nonplanarity, which is not representable with a single
                # BSP plane. Also detect previously co-planar polygons diverging.
                errors=[plane_distance(equation,self.vertices[r].xyz)
                        for r in poly.unique_refs]
                if max(errors, default=0) > 1.0:
                    raise FormatError(f"edited polygon is nonplanar ({max(errors):.1f} units)")
                # A shared split plane must still describe all originally
                # coincident descendant faces, else its ordering may be wrong.
                other=[self.polygons[x] for x in pl.candidates if x!=pl.anchor
                       and x in local]
                deviations=[plane_distance(equation,self.vertices[r].xyz)
                            for q in other for r in q.unique_refs]
                if deviations and max(deviations)>1.0:
                    raise FormatError(f"coincident descendant surface diverged ({max(deviations):.1f} units)")
                struct.pack_into('<3iq',patched,self.body_start+pl.offset+4,*equation)
                report.updated_planes+=1
            except (FormatError,OverflowError,ValueError) as exc:
                report.untouched_planes+=1
                report.warnings.append(f"{NAMES[pl.kind]} at {pl.offset}: {exc}; plane unchanged")
        unlinked=modified-associated
        if unlinked:
            report.warnings.append(
                f"{len(unlinked)} edited vertices have no originally coplanar "
                f"FACE/BSP match; any relevant non-surface split planes remain untouched")
        return bytes(patched),report

    def write(self, path):
        data,report=self.build_modified_bytes()
        out=Path(path)
        out.write_bytes(data)
        return report
