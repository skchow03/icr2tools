"""Conservative append-and-repoint polygon splitting for ICR2 3DO v3.

A split is defined by two *different polygon edges* and interpolation fractions.
The old polygon and all existing offsets remain in the binary, with parents
repointed to a new ordered LIST of two new polygons. Adjacent polygons which
share the *same vertex offsets* receive collinear boundary inserts by being
replaced with appended polygons too. No BSP/LOD record is moved or rebuilt.
"""
from __future__ import annotations
from dataclasses import dataclass
import struct
from three_do import FormatError, INT32_LO, INT32_HI

@dataclass(frozen=True)
class SplitResult:
    original_polygon: int
    new_polygons: tuple[int, int]
    replacement_list: int
    new_vertices: tuple[int, ...]
    updated_neighbors: tuple[tuple[int, int], ...]
    warnings: tuple[str, ...]


def _point(a, b, fraction):
    # fractions are plain floats for the UI, but all resulting coordinates
    # are exact integers in the serialized 3DO.
    return tuple(round(x + (y-x)*fraction) for x,y in zip(a,b))


def _polygon_record(kind, refs, color, group):
    if len(refs)<3 or len(set(refs))<3:
        raise FormatError('New polygon must contain at least three distinct vertices')
    if len(refs)>250000:
        raise FormatError('Polygon contains too many vertices')
    head=struct.pack('<I', 0x80000000 | kind)
    if kind==1:
        return head+struct.pack('<2i',color,len(refs)-1)+struct.pack(f'<{len(refs)}i',*refs)
    if kind==2:
        return head+struct.pack('<3i',group,color,len(refs)-1)+struct.pack(f'<{len(refs)}i',*refs)
    raise FormatError('Only POLY and POLY [T] may be split')


def _parent_slots(model, parent):
    """List (byte offset, original child pointer) for every actual link.

    Crucially, record slots are derived from *flavor metadata*, not from
    scanning 4-byte occurrences (which would corrupt coordinates or planes).
    """
    tag=model.records[parent]
    if tag in (5,6,7,8,9,10):
        count={5:1,6:2,7:3,8:3,9:4,10:2}[tag]
        offsets=[parent+24+4*i for i in range(count)]
    elif tag==11:
        count=struct.unpack_from('<i',model.body,parent+4)[0]
        offsets=[parent+8+4*i for i in range(count)]
    elif tag==13:
        offsets=[parent+12+8*i for i in range(len(model.switches[parent].branches))]
    elif tag==16:
        count=struct.unpack_from('<i',model.body,parent+8)[0]
        offsets=[parent+4]+[parent+12+4*i for i in range(count)]
    elif tag==4:
        offsets=[parent+12]
    else:
        offsets=[]
    return [(off,struct.unpack_from('<i',model.body,off)[0]) for off in offsets]


def _replace_parents(model, body, old, replacement):
    slots=[]
    for parent in model.records:
        for location,pointer in _parent_slots(model,parent):
            if pointer==old:
                slots.append(location)
    if not slots and model.root_offset!=old:
        raise FormatError(f'POLY {old} has no parent pointer to redirect')
    for slot in slots:
        struct.pack_into('<i',body,slot,replacement)
    return len(slots)


def split_bytes(model, polygon_offset, edge_a, edge_b, fraction_a=.5,
                fraction_b=.5, *, update_neighbors=True):
    """Return (complete 3DO bytes, SplitResult), without changing `model`.

    Edges are 0-based indexes: edge i runs vertex i -> vertex (i+1)%n.
    Adjacent faces sharing edge *references* are updated with matching
    interpolated points. UV seams using different refs are flagged for review.
    """
    if polygon_offset not in model.polygons:
        raise FormatError('Select a POLY before splitting')
    poly=model.polygons[polygon_offset]
    refs=list(poly.refs)
    if len(refs)>3 and refs[0]==refs[-1]:
        # This variant is not observed in stock cars and would need explicit
        # closing-reference preservation to avoid changing winding semantics.
        raise FormatError('Closed polygon vertex loops are not supported in v1.6')
    n=len(refs)
    if len(set(refs)) != n or n<3:
        raise FormatError('Splitting polygons with duplicate vertex references is not supported')
    try:
        ea,eb=int(edge_a),int(edge_b)
        ta,tb=float(fraction_a),float(fraction_b)
    except (ValueError,TypeError,OverflowError) as exc:
        raise FormatError('Invalid edge number or fraction') from exc
    if ea==eb or not (0<=ea<n and 0<=eb<n):
        raise FormatError('Choose two different polygon edges')
    if not (0.0 < ta < 1.0 and 0.0 < tb < 1.0):
        raise FormatError('Split fractions must be strictly between 0 and 1')
    for index,fraction in ((ea,ta),(eb,tb)):
        a=model.vertices[refs[index]].xyz; b=model.vertices[refs[(index+1)%n]].xyz
        if a==b or _point(a,b,fraction) in (a,b):
            raise FormatError(f'Edge {index+1} is too short to insert a distinct integer vertex')

    # Using the *currently effective* original+coordinate/BSP changes ensures
    # split operations are transactional with earlier unsaved edits.
    unmodified,old_report=model.build_modified_bytes()
    prefix=bytearray(unmodified[:model.body_start])
    body=bytearray(unmodified[model.body_start:])
    warnings=[]
    created_vertices=[]
    def append(data):
        if len(body) & 3:
            body.extend(b'\0' * ((-len(body))&3))
        off=len(body)
        if off > INT32_HI-len(data):
            raise FormatError('3DO exceeds signed 32-bit body-offset limit')
        body.extend(data)
        return off

    insertions={}
    for edge,fraction in ((ea,ta),(eb,tb)):
        x=model.vertices[refs[edge]]
        y=model.vertices[refs[(edge+1)%n]]
        xyz=_point(x.xyz,y.xyz,fraction)
        textured=poly.kind==2
        uv=_point(x.uv,y.uv,fraction) if textured else None
        if textured and (x.uv is None or y.uv is None):
            raise FormatError('Textured polygon has missing UV coordinates')
        buf=struct.pack('<4i',0,*xyz)
        if textured:
            if any(not 0<=v<=65535 for v in uv):
                raise FormatError('Interpolated UV outside unsigned 16-bit range')
            buf+=struct.pack('<2H',*uv)
        new_ref=append(buf)
        insertions[edge]=new_ref
        created_vertices.append(new_ref)

    expanded=[]
    for idx,ref in enumerate(refs):
        expanded.append(ref)
        if idx in insertions:
            expanded.append(insertions[idx])
    start=expanded.index(insertions[ea]); stop=expanded.index(insertions[eb])
    def circle_path(a,b):
        out=[expanded[a]]
        while a!=b:
            a=(a+1)%len(expanded)
            out.append(expanded[a])
        return out
    halves=[circle_path(start,stop),circle_path(stop,start)]
    for half in halves:
        if len(set(half))<3:
            raise FormatError('Split creates a polygon with fewer than three vertices')
    new_poly=[append(_polygon_record(poly.kind,half,poly.color,poly.group)) for half in halves]
    list_offset=append(struct.pack('<Ii2i',0x8000000b,2,*new_poly))
    count=_replace_parents(model,body,polygon_offset,list_offset)
    if count==0:  # unusual root-is-POLY case
        struct.pack_into('<i',prefix,4,list_offset)

    neighbors=[]
    if update_neighbors:
        # Only exact shared *edge references* are repaired. The same refs may
        # appear in either orientation; newly inserted coords are shared so
        # no crack is introduced even though each neighbor has its own record.
        affected={}
        for noff,other in model.polygons.items():
            if noff==polygon_offset:continue
            insert_by_edge={}
            rr=list(other.refs)
            for j in range(len(rr)):
                a,b=rr[j],rr[(j+1)%len(rr)]
                for k in (ea,eb):
                    source_a=refs[k]; source_b=refs[(k+1)%n]
                    if (a,b)==(source_a,source_b):
                        insert_by_edge[j]=(k,False)
                    elif (a,b)==(source_b,source_a):
                        insert_by_edge[j]=(k,True)
            if insert_by_edge:
                affected[noff]=insert_by_edge
        for noff,edges in affected.items():
            other=model.polygons[noff]
            outrefs=[]
            for j,ref in enumerate(other.refs):
                outrefs.append(ref)
                if j in edges:
                    k,reversed_direction=edges[j]
                    # A textured neighbor may use a different UV table than
                    # the target; create a new neighbor vertex for that seam.
                    existing=insertions[k]
                    if other.kind==poly.kind or poly.kind==2:
                        outrefs.append(existing)
                    else:
                        source_v=model.vertices[existing] if existing in model.vertices else None
                        # Target vertex is untextured, neighbor textured;
                        # compute a corresponding UV and allocate its own.
                        frac=(1-(ta if k==ea else tb)) if reversed_direction else (ta if k==ea else tb)
                        va=model.vertices[other.refs[j]]
                        vb=model.vertices[other.refs[(j+1)%len(other.refs)]]
                        xyz=_point(va.xyz,vb.xyz,frac)
                        uv=_point(va.uv,vb.uv,frac)
                        fresh=append(struct.pack('<4i2H',0,*xyz,*uv))
                        created_vertices.append(fresh)
                        outrefs.append(fresh)
            replacement=append(_polygon_record(other.kind,outrefs,other.color,other.group))
            _replace_parents(model,body,noff,replacement)
            neighbors.append((noff,replacement))
    # Warn about coordinate-shared edges whose endpoints are duplicated as
    # separate vertex records (e.g. texture seams). Do not silently join them.
    for k in (ea,eb):
        pa=model.vertices[refs[k]].xyz;pb=model.vertices[refs[(k+1)%n]].xyz
        for p in model.polygons.values():
            if p.offset==poly.offset or any(p.offset==old for old,_ in neighbors):continue
            rr=p.refs
            if any({model.vertices[a].xyz,model.vertices[b].xyz}=={pa,pb}
                   for a,b in zip(rr,rr[1:]+rr[:1])):
                warnings.append(f'POLY {p.offset} shares cut edge {k+1} geometrically but not by vertex references; inspect UV seam/LOD')
                break

    struct.pack_into('<i',prefix,0,len(body))
    out=bytes(prefix+body)
    return out,SplitResult(polygon_offset,tuple(new_poly),list_offset,
                           tuple(created_vertices),tuple(neighbors),tuple(warnings))


def _project_for_split(points):
    """Project a (possibly slightly warped) polygon onto its dominant plane."""
    normal = [0, 0, 0]
    for p, q in zip(points, points[1:] + points[:1]):
        normal[0] += (p[1] - q[1]) * (p[2] + q[2])
        normal[1] += (p[2] - q[2]) * (p[0] + q[0])
        normal[2] += (p[0] - q[0]) * (p[1] + q[1])
    axis = max(range(3), key=lambda i: abs(normal[i]))
    if normal[axis] == 0:
        raise FormatError('Polygon has no stable projected area')
    keep = [i for i in range(3) if i != axis]
    return [(p[keep[0]], p[keep[1]]) for p in points]


def _cross2(a, b, c):
    return ((b[0] - a[0]) * (c[1] - a[1]) -
            (b[1] - a[1]) * (c[0] - a[0]))


def _on_segment(a, b, p):
    return (_cross2(a, b, p) == 0 and
            min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and
            min(a[1], b[1]) <= p[1] <= max(a[1], b[1]))


def _intersects(a, b, c, d):
    s1, s2 = _cross2(a, b, c), _cross2(a, b, d)
    s3, s4 = _cross2(c, d, a), _cross2(c, d, b)
    if s1 * s2 < 0 and s3 * s4 < 0:
        return True
    return ((s1 == 0 and _on_segment(a, b, c)) or
            (s2 == 0 and _on_segment(a, b, d)) or
            (s3 == 0 and _on_segment(c, d, a)) or
            (s4 == 0 and _on_segment(c, d, b)))


def _area2(points):
    return sum(a[0]*b[1] - b[0]*a[1]
               for a, b in zip(points, points[1:] + points[:1]))


def _diagonal_is_inside(points, first, second):
    """Reject exterior/crossing diagonals on concave polygons.

    A midpoint inclusion test combined with edge intersections is sufficient
    for a straight internal diagonal of a simple polygon. Geometry remains
    unprojected in the output; this check only validates topology.
    """
    n = len(points)
    a, b = points[first], points[second]
    if a == b:
        return False
    for j in range(n):
        k = (j+1) % n
        if j in (first, second) or k in (first, second):
            continue
        if _intersects(a, b, points[j], points[k]):
            return False
    # midpoint winding (cross-products on doubled coordinates avoid fractions)
    mx, my = a[0] + b[0], a[1] + b[1]
    scaled = [(x*2, y*2) for x, y in points]
    inside = False
    for p, q in zip(scaled, scaled[1:] + scaled[:1]):
        if _on_segment(p, q, (mx, my)):
            return False
        if (p[1] > my) != (q[1] > my):
            crossing = (q[0]-p[0]) * (my-p[1]) / (q[1]-p[1]) + p[0]
            if mx < crossing:
                inside = not inside
    return inside


def split_existing_vertices_bytes(model, polygon_offset, index_a, index_b):
    """Split a polygon along two existing vertices; add NO vertex records.

    Both indices are 0-based *positions in the polygon's ordered vertex list*,
    not 3DO body offsets. Outputs a replacement LIST referencing two appended
    POLY records, with all original records retained at their original offsets.
    """
    if polygon_offset not in model.polygons:
        raise FormatError('Select a POLY before splitting')
    poly = model.polygons[polygon_offset]
    refs = list(poly.refs)
    n = len(refs)
    if n < 4:
        raise FormatError('Splitting between existing vertices requires at least four vertices')
    if len(set(refs)) != n:
        raise FormatError('Duplicate or closing vertex references are not supported')
    try:
        a, b = int(index_a), int(index_b)
    except (ValueError, TypeError, OverflowError) as exc:
        raise FormatError('Select two vertices from the numbered polygon vertex list') from exc
    if not (0 <= a < n and 0 <= b < n):
        raise FormatError('Vertex numbers are outside this polygon')
    if a == b or (a-b) % n in (1, n-1):
        raise FormatError('Choose two nonadjacent vertices to make a diagonal')
    xyz = [model.vertices[ref].xyz for ref in refs]
    projected = _project_for_split(xyz)
    if not _diagonal_is_inside(projected, a, b):
        raise FormatError('Selected diagonal lies outside the polygon or crosses an edge')

    def arc(start, end):
        out = [refs[start]]
        while start != end:
            start = (start+1) % n
            out.append(refs[start])
        return out

    half1, half2 = arc(a, b), arc(b, a)
    def projected_area(indices):
        return _area2([projected[refs.index(i)] for i in indices])
    if not projected_area(half1) or not projected_area(half2):
        raise FormatError('Selected diagonal creates a zero-area polygon')

    # Read from the *effective* working model, including pending XYZ/UV/plane
    # and DYNAMIC edits, and let the user's undo stack roll it all back.
    current, _ = model.build_modified_bytes()
    prefix = bytearray(current[:model.body_start])
    body = bytearray(current[model.body_start:])
    def append(record):
        body.extend(b'\0' * ((-len(body)) & 3))
        off = len(body)
        if off > INT32_HI - len(record):
            raise FormatError('3DO exceeds signed 32-bit body-offset limit')
        body.extend(record)
        return off
    children = (append(_polygon_record(poly.kind, half1, poly.color, poly.group)),
                append(_polygon_record(poly.kind, half2, poly.color, poly.group)))
    replacement = append(struct.pack('<Ii2i', 0x8000000b, 2, *children))
    count = _replace_parents(model, body, polygon_offset, replacement)
    if count == 0:
        struct.pack_into('<i', prefix, 4, replacement)
    struct.pack_into('<i', prefix, 0, len(body))
    result = SplitResult(polygon_offset, children, replacement, (), (), ())
    return bytes(prefix + body), result
