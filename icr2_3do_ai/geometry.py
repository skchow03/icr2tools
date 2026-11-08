"""Read-only semantic geometry extraction from the existing 3DO CAD scene.

A component is an *edge-connected* set of polygons in one model instance.
Shared world-space coordinates alone do not establish connectivity: Papyrus
often intentionally duplicates points for seams, UVs, and draw-order control.
Every stable ID includes the source instance and original binary body offset.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from math import sqrt


def _bounds(points):
    if not points:
        return None
    return {
        "min": [min(p[j] for p in points) for j in range(3)],
        "max": [max(p[j] for p in points) for j in range(3)],
        "size": [max(p[j] for p in points) - min(p[j] for p in points)
                 for j in range(3)],
        "center": [(max(p[j] for p in points) + min(p[j] for p in points)) / 2
                   for j in range(3)],
    }


def _newell(points):
    """Return area and unit normal; no claim about BSP front/back semantics."""
    if len(points) < 3:
        return 0.0, None
    nx = ny = nz = 0.0
    for a, b in zip(points, points[1:] + points[:1]):
        nx += (a[1] - b[1]) * (a[2] + b[2])
        ny += (a[2] - b[2]) * (a[0] + b[0])
        nz += (a[0] - b[0]) * (a[1] + b[1])
    length = sqrt(nx * nx + ny * ny + nz * nz)
    if length <= 1e-12:
        return 0.0, None
    return length / 2, [nx / length, ny / length, nz / length]


class _Groups:
    def __init__(self):
        self.parent = {}

    def add(self, key):
        self.parent.setdefault(key, key)

    def find(self, key):
        parent = self.parent[key]
        if parent != key:
            self.parent[key] = self.find(parent)
        return self.parent[key]

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def analyze_geometry(scene):
    """Produce deterministic per-face source provenance, adjacency and groups.

    Returns (geometry_report, diagnostics). No renderer, MIP decoder, model
    mutation or source export is required.
    """
    faces = []
    diagnostics = []
    edges = defaultdict(list)
    union = _Groups()
    xyz_all = []
    for inst_id, instance in enumerate(scene.instances):
        model = instance.model
        for poly_offset in sorted(model.polygons):
            poly = model.polygons[poly_offset]
            face_id = f"i{inst_id}:p{poly_offset}"
            refs = list(poly.unique_refs)
            union.add(face_id)
            try:
                vertices = [model.vertices[ref] for ref in refs]
            except KeyError as exc:
                diagnostics.append({
                    "severity": "error", "code": "MISSING_VERTEX",
                    "record": face_id, "message": f"Missing local vertex {exc.args[0]}"})
                continue
            pts = [[float(v) for v in instance.transform.apply(vertex.xyz)]
                   for vertex in vertices]
            xyz_all.extend(pts)
            area, normal = _newell(pts)
            if area <= 1e-12:
                diagnostics.append({
                    "severity": "warning", "code": "DEGENERATE_POLYGON",
                    "record": face_id,
                    "message": "Zero-area polygon; may be intentional hidden geometry"})
            flat_id = scene.polygon_lookup.get((inst_id, poly_offset))
            local_mip = model.polygon_materials.get(poly_offset)
            material = (scene.geometry.polygon_materials.get(flat_id)
                        if flat_id is not None else None)
            material_source = (scene.geometry.polygon_sources.get(flat_id)
                               if flat_id is not None else None)
            uvs = [list(v.uv) if v.uv is not None else None for v in vertices]
            present_uvs = [uv for uv in uvs if uv is not None]
            if poly.kind == 2 and len(present_uvs) != len(uvs):
                diagnostics.append({
                    "severity": "error", "code": "MISSING_UV",
                    "record": face_id,
                    "message": "POLY[T] references a vertex without UV coordinates"})
            if poly.kind == 2 and not material:
                diagnostics.append({
                    "severity": "warning", "code": "UNASSIGNED_MIP",
                    "record": face_id,
                    "message": "Textured polygon has no resolved MATERIAL MIP name"})
            face = {
                "id": face_id, "instance_id": inst_id,
                "source_file": str(model.path),
                "record_offset": poly_offset, "kind": "POLY[T]" if poly.kind == 2 else "POLY",
                "group": poly.group, "original_palette_index": poly.color,
                "effective_palette_index": (
                    scene.geometry.polygons[flat_id].color if flat_id is not None
                    else poly.color),
                "vertex_offsets": refs,
                "vertex_ids": [f"i{inst_id}:v{r}" for r in refs],
                "vertices_world": pts, "uvs": uvs,
                "uv_bounds": ({
                    "min": [min(p[j] for p in present_uvs) for j in range(2)],
                    "max": [max(p[j] for p in present_uvs) for j in range(2)],
                } if present_uvs else None),
                "bounds": _bounds(pts),
                "centroid": ([sum(v[j] for v in pts) / len(pts) for j in range(3)]
                             if pts else None),
                "area_raw_units_squared": area,
                "winding_normal": normal,
                "material": material if poly.kind == 2 else None,
                "local_material": local_mip if poly.kind == 2 else None,
                "material_source": str(material_source) if material_source and poly.kind == 2 else None,
                "body_mip_override_eligible": bool(flat_id in scene.geometry.body_polygons)
                                              if flat_id is not None else False,
                "adjacent_polygon_ids": [],
                "component_id": None,
            }
            faces.append(face)
            if len(refs) >= 3:
                for a, b in zip(refs, refs[1:] + refs[:1]):
                    if a == b:
                        continue
                    # Vertex identity is local to a source 3DO instance.
                    key = (inst_id, min(a, b), max(a, b))
                    edges[key].append((face_id, a == key[1]))
    adjacent = defaultdict(set)
    edge_counts = Counter()
    for (inst, a, b), occurrences in edges.items():
        distinct = sorted({face_id for face_id, _ in occurrences})
        edge_counts[len(distinct)] += 1
        if len(distinct) >= 2:
            for fid in distinct[1:]:
                union.union(distinct[0], fid)
            for fid in distinct:
                adjacent[fid].update(other for other in distinct if other != fid)
        if len(distinct) > 2:
            diagnostics.append({
                "severity": "warning", "code": "NONMANIFOLD_EDGE",
                "record": f"i{inst}:v{a}-v{b}",
                "related_polygons": distinct,
                "message": "More than two polygons share this topological edge"})
    comps = defaultdict(list)
    by_id = {face["id"]: face for face in faces}
    for face in faces:
        face["adjacent_polygon_ids"] = sorted(adjacent[face["id"]])
        comps[(face["instance_id"], union.find(face["id"]))].append(face["id"])
    groups = []
    component_number = defaultdict(int)
    for inst_id, root in sorted(comps, key=lambda x: (x[0], min(comps[x]))):
        member_ids = sorted(comps[inst_id, root])
        group_id = f"i{inst_id}:c{component_number[inst_id]}"
        component_number[inst_id] += 1
        members = [by_id[x] for x in member_ids]
        for p in members:
            p["component_id"] = group_id
        pts = [pt for p in members for pt in p["vertices_world"]]
        groups.append({
            "id": group_id, "instance_id": inst_id,
            "source_file": str(scene.instances[inst_id].model.path),
            "polygon_count": len(members),
            "polygon_ids": member_ids,
            "textured_polygons": sum(p["kind"] == "POLY[T]" for p in members),
            "bounds": _bounds(pts),
            "materials": dict(sorted(Counter(
                p["material"] for p in members if p["material"]).items())),
            "total_polygon_area_raw_units_squared":
                sum(p["area_raw_units_squared"] for p in members),
        })
    return {
        "units": "Papyrus raw units; no feet/meters conversion assumed",
        "connectivity_rule": "shared original vertex-offset edge within one instance",
        "bounds": _bounds(xyz_all),
        "polygon_count": len(faces),
        "component_count": len(groups),
        "edge_counts": {
            "boundary": edge_counts.get(1, 0),
            "shared_by_two": edge_counts.get(2, 0),
            "shared_by_three_or_more": sum(
                count for n, count in edge_counts.items() if n > 2),
        },
        "polygons": faces, "components": groups,
    }, diagnostics
