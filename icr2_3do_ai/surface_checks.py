"""Conservative Stage 2 surface-overlap diagnostics, no mesh mutation.

Only resolved source components are examined. An exact duplicate (including
reversed winding), a positive-area coplanar overlap, or a noncoplanar polygon
intersection may cause painter-order defects. Coincident shared edges or
single-vertex contacts do not qualify as overlapping surfaces.

This is a geometric preflight, not a hidden-surface removal algorithm, BSP
validator, or general watertight/solid-boolean intersection implementation.
"""
from __future__ import annotations

from math import gcd

MAX_CANDIDATE_PAIRS = 50000
MAX_REPORTS = 100


def _dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def _sub(a, b):
    return tuple(x-y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1]*b[2]-a[2]*b[1],
            a[2]*b[0]-a[0]*b[2],
            a[0]*b[1]-a[1]*b[0])


def _plane(points):
    for i in range(1, len(points)-1):
        n = _cross(_sub(points[i], points[0]),
                   _sub(points[i+1], points[0]))
        if any(n):
            scale = gcd(gcd(abs(n[0]), abs(n[1])), abs(n[2]))
            n = tuple(v//scale for v in n)
            if next(v for v in n if v) < 0:
                n = tuple(-v for v in n)
            return n, _dot(n, points[0])
    return None


def _bounds(points):
    return tuple((min(p[i] for p in points), max(p[i] for p in points))
                 for i in range(3))


def _touch(a, b):
    return all(x[0] <= y[1] and y[0] <= x[1]
               for x, y in zip(a, b))


def _project(points, normal):
    drop = max(range(3), key=lambda i: abs(normal[i]))
    use = [i for i in range(3) if i != drop]
    return [(float(p[use[0]]), float(p[use[1]])) for p in points]


def _area2(poly):
    return sum(a[0]*b[1]-b[0]*a[1]
               for a, b in zip(poly, poly[1:]+poly[:1]))


def _inside(point, a, b, sign, *, strict=False):
    cross = (b[0]-a[0])*(point[1]-a[1])-(b[1]-a[1])*(point[0]-a[0])
    return cross*sign > 1e-7 if strict else cross*sign >= -1e-7


def _clipped_area(subject, clip):
    """Area of convex polygon intersection, excluding boundary-only contact."""
    if len(subject) < 3 or len(clip) < 3:
        return 0.0
    sign = 1 if _area2(clip) > 0 else -1
    output = list(subject)
    for a, b in zip(clip, clip[1:]+clip[:1]):
        previous = output
        output = []
        if not previous:
            return 0.0
        for p, q in zip(previous, previous[1:]+previous[:1]):
            start_inside = _inside(p, a, b, sign)
            end_inside = _inside(q, a, b, sign)
            if start_inside != end_inside:
                edge = (q[0]-p[0], q[1]-p[1])
                border = (b[0]-a[0], b[1]-a[1])
                denominator = edge[0]*border[1]-edge[1]*border[0]
                if abs(denominator) > 1e-12:
                    t = ((a[0]-p[0])*border[1]-
                         (a[1]-p[1])*border[0])/denominator
                    output.append((p[0]+t*edge[0], p[1]+t*edge[1]))
            if end_inside:
                output.append(q)
    return abs(_area2(output))/2 if len(output) >= 3 else 0.0


def _strict_inside_convex(point, poly, normal):
    """True only if point lies strictly within the projected polygon."""
    section = _project(poly, normal)
    probe = _project([point], normal)[0]
    sign = 1 if _area2(section) > 0 else -1
    return all(_inside(probe, a, b, sign, strict=True)
               for a, b in zip(section, section[1:]+section[:1]))


def _edge_crosses_surface(points, other, other_plane):
    """Detect an edge crossing through the interior of the other polygon."""
    normal, constant = other_plane
    distances = [_dot(normal, v)-constant for v in points]
    for i, (p, q) in enumerate(zip(points, points[1:]+points[:1])):
        a, b = distances[i], distances[(i+1)%len(points)]
        if a*b >= 0:
            continue
        proportion = a/(a-b)
        hit = tuple(p[j]+proportion*(q[j]-p[j]) for j in range(3))
        if _strict_inside_convex(hit, other, normal):
            return True
    return False


def _crossing(a, b):
    # Distinct planes whose polygon edges penetrate the opposite interior.
    return (_edge_crosses_surface(a["pts"], b["pts"], b["plane"]) or
            _edge_crosses_surface(b["pts"], a["pts"], a["plane"]))


def find_surface_conflicts(components):
    """Return bounded, deterministic warnings for suspicious authoring geometry.

    Strict validation is opt-in at the recipe level. Touching edges, intentional
    seams, and adjacent triangles within one component are excluded. The scan
    is guarded against quadratic blow-ups on large coplanar car models.
    """
    faces = []
    for component in components:
        for index, refs in enumerate(component.faces):
            points = [component.vertices[i] for i in refs]
            plane = _plane(points)
            if plane is None:
                continue
            faces.append({
                "part": component.name, "index": index,
                "pts": points, "plane": plane,
                "bounds": _bounds(points),
                "unique_vertices": tuple(sorted(set(points))),
            })
    # Report distinct *component pairs*, not every contacting triangle.
    # Suspension and chassis meshes deliberately intersect and can generate
    # hundreds of nearly identical reports. Prioritize duplicate/embedded
    # skins so meaningful bonnet/cowl issues are never buried by those.
    groups = {}
    count = 0
    truncated_scan = False
    ordered = sorted(faces, key=lambda f: (f["bounds"][0][0],
                                         f["part"], f["index"]))
    for i, a in enumerate(ordered):
        if truncated_scan:
            break
        for b in ordered[i+1:]:
            if b["bounds"][0][0] > a["bounds"][0][1]:
                break
            if a["part"] == b["part"] or not _touch(a["bounds"], b["bounds"]):
                continue
            count += 1
            if count > MAX_CANDIDATE_PAIRS:
                truncated_scan = True
                break
            if a["unique_vertices"] == b["unique_vertices"]:
                code = "DUPLICATE_SURFACE"
            elif a["plane"] == b["plane"]:
                projected_a = _project(a["pts"], a["plane"][0])
                projected_b = _project(b["pts"], b["plane"][0])
                code = ("COPLANAR_OVERLAP"
                        if _clipped_area(projected_a, projected_b) > 1e-5
                        else None)
            else:
                code = "INTERSECTING_SURFACES" if _crossing(a, b) else None
            if code is None:
                continue
            if a["part"] < b["part"]:
                parts, ids = (a["part"], b["part"]), (a["index"], b["index"])
            else:
                parts, ids = (b["part"], a["part"]), (b["index"], a["index"])
            key = (code, *parts)
            if key not in groups:
                groups[key] = {
                    "code": code, "severity": "warning",
                    "components": list(parts),
                    "polygons": list(ids),
                    "occurrences": 0,
                    "message": ("Possible duplicate/overlapping source surfaces; "
                                "review before retaining both components"),
                }
            groups[key]["occurrences"] += 1

    priority = {"DUPLICATE_SURFACE": 0, "COPLANAR_OVERLAP": 1,
                "INTERSECTING_SURFACES": 2}
    reports = sorted(
        groups.values(),
        key=lambda x: (priority[x["code"]], *x["components"])
    )
    if len(reports) > MAX_REPORTS:
        reports = reports[:MAX_REPORTS] + [{
            "code": "SURFACE_REPORT_LIMIT", "severity": "warning",
            "message": (f"Only the first {MAX_REPORTS} component-pair findings "
                        "are shown, sorted by collision severity"),
        }]
    if truncated_scan:
        reports.append({
            "code": "SURFACE_SCAN_LIMIT", "severity": "warning",
            "message": (f"Stopped after {MAX_CANDIDATE_PAIRS} candidate pairs; "
                        "remaining surfaces were not checked"),
        })
    return reports
