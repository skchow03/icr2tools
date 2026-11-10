"""Directional front-face culling for Marmon Wasp exterior roof and cockpit lips.

N3 POLY is double-sided by default. A source winding/normal does not by itself
remove the inward-facing triangle. Wrap each upward-facing surface in a native
FACE node; do not change coordinates, palette, painter order, or V29 baselines.
"""
from __future__ import annotations

from collections import defaultdict
from math import sqrt
import re

_VERTEX = re.compile(r"(?m)^([A-Za-z]\w*): \[<(-?\d+), (-?\d+), (-?\d+)>\];$")
_POLY = re.compile(r"(?m)^([A-Za-z]\w*): POLY <(\d+)> \{([^}\n]+)\};$")
_GROUP = r"(?m)^({}: LIST \{{)([^}}\n]+)(\}};)$"
TOTAL_TOP_FACES = 56


def _normal(a, b, c):
    ab = tuple(b[i] - a[i] for i in range(3))
    ac = tuple(c[i] - a[i] for i in range(3))
    return (ab[1]*ac[2] - ab[2]*ac[1],
            ab[2]*ac[0] - ab[0]*ac[2],
            ab[0]*ac[1] - ab[1]*ac[0])


def top_surface_names():
    roofs = {
        "wasp_tail_roof_geo": [
            f"pointed_tail_p{12*span+i:04}" for span in range(3)
            for i in range(5, 11)],
        "wasp_bonnet_roof_geo": [
            f"long_bonnet_p{12*span+i:04}" for span in range(3)
            for i in range(5, 11)],
    }
    for side in ("left", "right"):
        for span in range(1, 6):
            base = f"cockpit_body_{side}_{span}"
            roofs[base + "_geo"] = [f"{base}_p0003", f"{base}_p0004"]
    assert sum(map(len, roofs.values())) == TOTAL_TOP_FACES
    return roofs


def apply_top_face_culling(source):
    """Wrap 36 roof and 20 lip triangles in exact outward-wound FACE gates."""
    verts = {
        m[1]: tuple(int(m[i]) for i in (2, 3, 4))
        for m in _VERTEX.finditer(source)
    }
    polygons = {m[1]: m[3].split(", ") for m in _POLY.finditer(source)}
    roof_groups = top_surface_names()
    if "wasp_top_frontface_" in source:
        raise ValueError("Top FACE culling has already been applied")
    records = []
    gate_lines = [
        "% V30c: one-sided exterior bonnet/tail roofs and cockpit armrest tops.",
        "% Gate winding is exactly the three outward-wound triangle vertices.",
    ]
    for group, members in roof_groups.items():
        matcher = re.search(_GROUP.format(re.escape(group)), source)
        if matcher is None:
            raise ValueError(f"Missing V30 roof/lip list: {group}")
        existing = [p.strip() for p in matcher[2].split(",")]
        if any(existing.count(p) != 1 for p in members):
            raise ValueError(f"Expected exactly one of each roof/lip polygon in {group}")
        revised = []
        for p in existing:
            if p not in members:
                revised.append(p)
                continue
            refs = polygons[p]
            if len(refs) != 3 or len(set(refs)) != 3:
                raise ValueError(f"Expected an independent top triangle: {p}")
            triangle = [verts[name] for name in refs]
            n = _normal(*triangle)
            if n[2] <= 0:
                raise ValueError(f"Top triangle not upward-facing: {p}, normal={n}")
            gate = "wasp_top_frontface_" + p
            revised.append(gate)
            gate_lines.append(
                f"{gate}: FACE ({', '.join(refs)}), {p};")
            records.append({"polygon": p, "gate": gate, "vertices": triangle,
                            "normal": n, "group": group})
        source = (source[:matcher.start(2)]
                  + ", ".join(revised) + source[matcher.end(2):])
    if len(records) != TOTAL_TOP_FACES:
        raise ValueError(f"Wrong top FACE count: {len(records)}")
    return source + "\n" + "\n".join(gate_lines) + "\n", records


def check_compiled_top_culling(model, records):
    """Verify compiled FACE reachability on both sides of every roof/lip plane.

    A failed inward-facing camera must not reach its polygon; this is stronger
    than checking painter position, since invisible inner faces can be painted
    over by other components and still cause scanline artifacts in-game.
    """
    if len(records) != TOTAL_TOP_FACES:
        raise ValueError("Missing top-cull records")
    compiled = defaultdict(list)
    for poly in model.polygons.values():
        xyz = tuple(sorted({model.vertices[v].xyz for v in poly.refs}))
        compiled[xyz].append(poly.offset)
    faces = [plane for plane in model.planes.values() if plane.kind == 5]
    if len(faces) != 22 + TOTAL_TOP_FACES:
        raise ValueError(f"Expected 78 total FACE nodes, got {len(faces)}")
    face_children = defaultdict(list)
    for face in faces:
        for child in model.children.get(face.offset, []):
            face_children[child].append(face.offset)
    report = {"top_gates": len(records), "front_sample_tests": 0,
              "back_sample_tests": 0, "groups": {}}
    for item in records:
        xyz = item["vertices"]
        key = tuple(sorted(xyz))
        offsets = compiled[key]
        if len(offsets) != 1 or len(face_children[offsets[0]]) != 1:
            raise ValueError(f"Missing or duplicate compiled FACE for {item['polygon']}")
        face = next(f for f in faces if f.offset == face_children[offsets[0]][0])
        # The compiled gate's plane should point upward with the source winding.
        if face.equation[2] <= 0:
            raise ValueError(f"Compiled FACE winding inverted: {item['polygon']}")
        n = item["normal"]
        mag = sqrt(sum(float(v)*v for v in n))
        centroid = tuple(sum(p[i] for p in xyz) / 3 for i in range(3))
        for side in (1, -1):
            eye = tuple(round(centroid[i] + side*60000*n[i]/mag)
                        for i in range(3))
            selected, _, _ = model.switched_polygons(
                None, eye, bsp_mode="original")
            present = offsets[0] in set(selected)
            if present != (side == 1):
                raise ValueError(
                    f"Incorrect {item['polygon']} FACE from {eye}: "
                    f"normal={n}, visible={present}, expected={side == 1}")
            report["front_sample_tests" if side == 1
                   else "back_sample_tests"] += 1
        group = item["group"]
        report["groups"][group] = report["groups"].get(group, 0) + 1
    return report
