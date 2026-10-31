"""Append-and-repoint 3DO geometry insertion, preserving existing byte offsets.

All additions are reachable through precisely one selected parent pointer slot.
The original LIST is unchanged, and every new vertex is referenced by a POLY.
One-sided FACE and two-sided FACE2 children use a new explicit plane.
"""
from __future__ import annotations
from dataclasses import dataclass
import struct
import math
from three_do import FormatError, INT32_HI, INT32_LO, INT64_HI, INT64_LO, cross, sub, dot
from topology_split import _polygon_record, _parent_slots


@dataclass(frozen=True)
class GeometryResult:
    original_polygon: int
    new_polygons: tuple[int, ...]
    replacement_list: int
    new_vertices: tuple[int, ...]
    updated_neighbors: tuple[tuple[int,int], ...] = ()
    warnings: tuple[str, ...] = ()
    face_offset: int = -1
    patched_slot: int = -1
    source_list: int = -1
    # Existing split-report fields allow the save report to describe additions.


def list_insert_targets(model, anchor_polygon):
    """Return (list, child_position, parent_node, pointer_slot) candidates.

    A candidate is included only if the selected polygon descends from exactly
    one child of the LIST. This prevents ambiguous placement by ancestry.
    The chosen link updates one parent slot, never every occurrence of a LIST.
    """
    if anchor_polygon not in model.polygons:
        return []
    def includes(root, target):
        seen=set(); pending=[root]
        while pending:
            p=pending.pop()
            if p==target: return True
            if p in seen:continue
            seen.add(p)
            pending.extend(x for x in model.children.get(p,()) if x>0)
        return False
    candidates=[]
    for off,kind in model.records.items():
        if kind!=11:continue
        hits=[i for i,c in enumerate(model.children.get(off,())) if includes(c,anchor_polygon)]
        if len(hits)!=1:continue
        for parent in model.records:
            for slot,ptr in _parent_slots(model,parent):
                if ptr==off:
                    candidates.append((off,hits[0],parent,slot))
        if model.root_offset==off:
            candidates.append((off,hits[0],-1,-1))
    def distance(parent):
        # Favor LISTs nearest the selected POLY; a direct child is best.
        node=parent[0]; child=model.children[node][parent[1]]
        work=[(child,0)]; visited=set()
        while work:
            p,d=work.pop(0)
            if p==anchor_polygon:return d
            if p in visited:continue
            visited.add(p)
            work.extend((x,d+1) for x in model.children.get(p,()) if x>0)
        return 9999
    return sorted(candidates,key=lambda p:(distance(p),p[0],p[2],p[3]))


def _normal_plane(points):
    """Preserve point ordering; build exact integer plane with bounded normal."""
    p0=points[0]
    best=None; norm2=0
    for i in range(1,len(points)-1):
        for j in range(i+1,len(points)):
            n=cross(sub(points[i],p0),sub(points[j],p0))
            size=dot(n,n)
            if size>norm2:best=n;norm2=size
    if not norm2:raise FormatError('New polygon has no noncollinear vertex triplet')
    # Scale the normal into a modest, stable signed-int coefficient range.
    maxval=max(abs(k) for k in best)
    abc=tuple(int(math.copysign(max(1,(abs(k)*65536+maxval//2)//maxval),k)) if k else 0 for k in best)
    d=-dot(abc,p0)
    if not all(INT32_LO<=i<=INT32_HI for i in abc) or not INT64_LO<=d<=INT64_HI:
        raise FormatError('New plane cannot fit signed 32-bit/64-bit coefficients')
    length=math.sqrt(norm2)
    maximum=max(abs(dot(best,p)-dot(best,p0))/length for p in points)
    return (*abc,d),maximum


def create_polygon_bytes(model, anchor_polygon, list_offset, child_index,
                         parent_offset, pointer_slot, vertices, *, color=40,
                         group=0, textured=False, two_sided=True,
                         after=True):
    """Create new geometry under an explicit LIST insertion occurrence.

    vertices: iterable of either existing vertex offsets or (x,y,z[,u,v])
    tuples. All new vertices are referenced immediately; none are orphaned.
    """
    valid=set(list_insert_targets(model,anchor_polygon))
    key=(list_offset,child_index,parent_offset,pointer_slot)
    if key not in valid:
        raise FormatError('Selected LIST insertion slot is no longer valid for this polygon')
    if len(vertices)<3 or len(vertices)>128:
        raise FormatError('New polygon must have 3 to 128 vertices')
    if not INT32_LO<=int(color)<=INT32_HI or not INT32_LO<=int(group)<=INT32_HI:
        raise FormatError('Color or texture group outside signed 32-bit range')
    current,_=model.build_modified_bytes()
    prefix=bytearray(current[:model.body_start]);body=bytearray(current[model.body_start:])
    refs=[];points=[];new=[]
    def append(data):
        body.extend(b'\0'*((-len(body))&3))
        off=len(body)
        if off>INT32_HI-len(data):raise FormatError('New 3DO body exceeds signed offset range')
        body.extend(data)
        return off
    for item in vertices:
        if isinstance(item,int):
            if item not in model.vertices:raise FormatError(f'Unknown existing vertex @{item}')
            v=model.vertices[item]
            if textured and not v.textured:
                raise FormatError(f'Vertex @{item} has no UV. Use a textured vertex or enter XYZUV.')
            ref=item;xyz=v.xyz
        else:
            vv=tuple(map(int,item))
            if len(vv)!=(5 if textured else 3):
                raise FormatError('Each new point needs XYZ (and UV when textured)')
            xyz=vv[:3]
            if not all(INT32_LO<=v<=INT32_HI for v in xyz):
                raise FormatError('New XYZ outside signed 32-bit range')
            if textured and any(not 0<=v<=65535 for v in vv[3:]):
                raise FormatError('New U/V must be 0–65535')
            buf=struct.pack('<4i',0,*xyz)
            if textured:buf+=struct.pack('<2H',*vv[3:])
            ref=append(buf);new.append(ref)
        refs.append(ref);points.append(xyz)
    if len(set(refs))!=len(refs):
        raise FormatError('Repeated vertex references are not supported; remove duplicates')
    eq,deviation=_normal_plane(points)
    kind=2 if textured else 1
    front=append(_polygon_record(kind,refs,int(color),int(group)))
    polys=[front]
    if two_sided:
        back=append(_polygon_record(kind,list(reversed(refs)),int(color),int(group)))
        polys.append(back)
        node=append(struct.pack('<I3iq2i',0x80000006,*eq,front,back))
    else:
        node=append(struct.pack('<I3iqi',0x80000005,*eq,front))
    children=list(model.children[list_offset])
    children.insert(child_index+(1 if after else 0),node)
    new_list=append(struct.pack(f'<Ii{len(children)}i',0x8000000b,len(children),*children))
    if parent_offset<0:
        if model.root_offset!=list_offset:
            raise FormatError('Selected root LIST has changed')
        struct.pack_into('<i',prefix,4,new_list)
    else:
        if not (0<=pointer_slot<len(model.body)-4):
            raise FormatError('Invalid parent pointer slot')
        if struct.unpack_from('<i',body,pointer_slot)[0]!=list_offset:
            raise FormatError('Parent pointer changed since insertion was selected')
        struct.pack_into('<i',body,pointer_slot,new_list)
    struct.pack_into('<i',prefix,0,len(body))
    warnings=[]
    if deviation>1.0:
        warnings.append(f'New polygon is nonplanar (maximum deviation {deviation:.1f} units); '
                        'FACE plane uses a best-area triplet. Verify front/back behavior.')
    warnings.append('New FACE geometry follows fixed LIST paint order; BSP-dependent near/far '
                    'occlusion is NOT automatic. Rotate the preview and check in-game.')
    return bytes(prefix+body),GeometryResult(anchor_polygon,tuple(polys),new_list,
              tuple(new),warnings=tuple(warnings),face_offset=node,
              patched_slot=pointer_slot,source_list=list_offset)


def create_model_polygon(model,*args,**kwargs):
    from three_do import Model
    data,result=create_polygon_bytes(model,*args,**kwargs)
    output=Model(model.path,raw_data=data,topology_history=(*model.topology_history,result))
    if not all(p in output.polygons for p in result.new_polygons):
        raise FormatError('New polygons are not reachable in the saved scene')
    if result.face_offset not in output.planes:
        raise FormatError('New FACE node is not reachable')
    if result.replacement_list not in output.records:
        raise FormatError('New LIST node is not reachable')
    for p in result.new_polygons:
        if output.polygons[p].refs != (tuple(reversed(output.polygons[result.new_polygons[0]].refs)) if p!=result.new_polygons[0] else output.polygons[p].refs):
            raise FormatError('New polygon reference order changed during round-trip')
    return output,result
