"""Deterministic parametric geometry -> editable Papyrus N3 source.

Stage 2 is deliberately a *source generator*, not an LLM or a 3DO binary
patcher. A strict JSON recipe describes convex cross-sections, extrusions and
reflections. The existing CAD N3 compiler remains the sole binary compiler.

All coordinate values in a recipe are converted to signed 32-bit Papyrus raw
integers before generating named vertex declarations. Quantization can make
tiny faces degenerate; these are rejected instead of silently omitted.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import re

SCHEMA = "icr2.n3.recipe.v1"
INT32_MIN, INT32_MAX = -(1 << 31), (1 << 31) - 1
NAME = re.compile(r"^[A-Za-z][A-Za-z_0-9]*$")
MIP = re.compile(r"^[A-Za-z_0-9]{1,8}$")
AXIS = {"x": 0, "y": 1, "z": 2}
PLANES = {"x": (1, 2), "y": (2, 0), "z": (0, 1)}
MAX_OPERATIONS = 128
MAX_VERTICES = 30000
MAX_FACES = 60000


class RecipeError(ValueError):
    """User-facing validation error; unsafe or ambiguous input is rejected."""


@dataclass
class Component:
    name: str
    vertices: list[tuple[int, int, int]]
    faces: list[tuple[int, ...]]
    color: int
    mip: str | None
    uv: dict | None
    # Whether the reflected copy should preserve the original UV orientation.
    # UVs are projected in world coordinates; mirroring may flip visual paint.
    source: str | None = None


def _fail(where, message):
    raise RecipeError(f"{where}: {message}")


def _object(value, where):
    if not isinstance(value, dict):
        _fail(where, "expected an object")
    return value


def _keys(value, allowed, required, where):
    unexpected = set(value) - set(allowed)
    missing = set(required) - set(value)
    if unexpected:
        _fail(where, f"unknown fields: {', '.join(sorted(unexpected))}")
    if missing:
        _fail(where, f"missing fields: {', '.join(sorted(missing))}")


def _number(value, where):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        _fail(where, "expected a finite decimal number")
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _fail(where, "invalid decimal number")
    if not decimal.is_finite():
        _fail(where, "NaN/Infinity is not allowed")
    return decimal


def _integer(value, where, minimum, maximum):
    numeric = _number(value, where)
    if numeric != numeric.to_integral_value():
        _fail(where, "expected an integer")
    num = int(numeric)
    if not minimum <= num <= maximum:
        _fail(where, f"expected integer between {minimum} and {maximum}")
    return num


def _raw(value, scale, where):
    numeric = (_number(value, where) * scale).to_integral_value(
        rounding=ROUND_HALF_EVEN)
    if numeric < INT32_MIN or numeric > INT32_MAX:
        _fail(where, "coordinate exceeds signed 32-bit Papyrus range")
    return int(numeric)


def _pair(value, where):
    if not isinstance(value, list) or len(value) != 2:
        _fail(where, "expected exactly two numbers")
    return [_number(v, f"{where}[{i}]") for i, v in enumerate(value)]


def _axis(value, where):
    if not isinstance(value, str) or value not in AXIS:
        _fail(where, "expected axis 'x', 'y', or 'z'")
    return value


def _name(value, where):
    if (not isinstance(value, str) or len(value) > 32 or
            not NAME.fullmatch(value) or value.lower() in {"root", "nil"}):
        _fail(where, "expected unique label (1-32 ASCII letters/digits/underscore, starting with a letter)")
    return value


def _mip(value, where):
    if value is None:
        return None
    if not isinstance(value, str) or not MIP.fullmatch(value):
        _fail(where, "MIP must be 1-8 ASCII alphanumeric/underscore characters")
    return value


def _optional_bool(value, where):
    if not isinstance(value, bool):
        _fail(where, "expected true or false")
    return value


def _convex_ring(ring, where):
    """Normalize polygon to CCW cross-section order, reject self intersections.

    Convex rings make polygon caps safe for this first source-generator version.
    Lofted shells can still have varying cross-sections, but are triangulated.
    """
    if not isinstance(ring, list) or not 3 <= len(ring) <= 64:
        _fail(where, "outline must contain 3-64 points")
    points = [_pair(pt, f"{where}[{i}]") for i, pt in enumerate(ring)]
    if len(set(map(tuple, points))) != len(points):
        _fail(where, "outline contains duplicate points")
    area2 = sum(a[0] * b[1] - b[0] * a[1]
                for a, b in zip(points, points[1:] + points[:1]))
    if area2 == 0:
        _fail(where, "outline has zero signed area")
    direction = 1 if area2 > 0 else -1
    for i in range(len(points)):
        a, b, c = (points[i + j if i + j < len(points) else i + j - len(points)]
                   for j in range(3))
        cross = ((b[0]-a[0]) * (c[1]-b[1])
                 - (b[1]-a[1]) * (c[0]-b[0]))
        if cross * direction <= 0:
            _fail(where, "only strictly convex, non-collinear outlines are supported")
    return points if direction > 0 else list(reversed(points))


def _rectangle(section, where):
    _keys(section, {"at", "center", "width", "height"}, {"at", "width", "height"}, where)
    center = _pair(section.get("center", [0, 0]), f"{where}.center")
    width = _number(section["width"], f"{where}.width")
    height = _number(section["height"], f"{where}.height")
    if width <= 0 or height <= 0:
        _fail(where, "width and height must be positive")
    u, v = center
    hw, hh = width / 2, height / 2
    return [[u-hw, v-hh], [u+hw, v-hh], [u+hw, v+hh], [u-hw, v+hh]]


def _to_xyz(axis, at, u, v, scale, where):
    result = [0, 0, 0]
    result[AXIS[axis]] = _raw(at, scale, where + ".at")
    other = PLANES[axis]
    result[other[0]] = _raw(u, scale, where + ".u")
    result[other[1]] = _raw(v, scale, where + ".v")
    return tuple(result)


def _length2(a, b, c):
    ax, ay, az = (b[i] - a[i] for i in range(3))
    bx, by, bz = (c[i] - a[i] for i in range(3))
    cross = (ay*bz-az*by, az*bx-ax*bz, ax*by-ay*bx)
    return sum(v*v for v in cross)


def _checked_faces(component, where):
    for i, face in enumerate(component.faces):
        if len(face) < 3 or len(set(face)) != len(face):
            _fail(where, f"face {i} repeats vertices or has fewer than 3")
        points = [component.vertices[index] for index in face]
        if any(a == b for a, b in zip(points, points[1:] + points[:1])):
            _fail(where, f"face {i} contains a collapsed edge after quantization")
        if not any(_length2(points[0], points[j], points[j+1]) > 0
                   for j in range(1, len(points)-1)):
            _fail(where, f"face {i} collapses after coordinate quantization")


def _uv_options(config, where):
    if config is None:
        return None
    config = _object(config, where)
    _keys(config, {"axes", "origin", "pixels_per_unit", "offset"},
          {"axes", "pixels_per_unit"}, where)
    axes = config["axes"]
    if (not isinstance(axes, list) or len(axes) != 2 or
            not all(isinstance(x, str) and x in AXIS for x in axes)
            or axes[0] == axes[1]):
        _fail(where, "axes must be two different values from x/y/z")
    origin = _pair(config.get("origin", [0, 0]), where + ".origin")
    factor = _pair(config["pixels_per_unit"], where + ".pixels_per_unit")
    offset = _pair(config.get("offset", [0, 0]), where + ".offset")
    if any(n == 0 for n in factor):
        _fail(where, "pixels_per_unit cannot be zero")
    return {"axes": axes, "origin": origin, "pixels_per_unit": factor,
            "offset": offset}


def _options(op, where):
    color = _integer(op.get("color", 40), where + ".color", 0, 255)
    mip = _mip(op.get("material"), where + ".material")
    uv = _uv_options(op.get("uv"), where + ".uv")
    if (mip is None) != (uv is None):
        _fail(where, "textured geometry requires both material and uv; omit both for solid POLY")
    caps = _optional_bool(op.get("caps", True), where + ".caps")
    return color, mip, uv, caps


def _rings(name, axis, segments, scale, color, mip, uv, caps, where):
    if not 2 <= len(segments) <= 128:
        _fail(where, "loft requires 2-128 cross-sections")
    rings = []
    previous = None
    width = None
    for i, (at, ring) in enumerate(segments):
        pos = _number(at, f"{where}.sections[{i}].at")
        if previous is not None and pos <= previous:
            _fail(where, "cross-sections must have strictly increasing positions")
        previous = pos
        points = _convex_ring(ring, f"{where}.sections[{i}].outline")
        if width is None:
            width = len(points)
        elif len(points) != width:
            _fail(where, "all cross-sections must have the same vertex count")
        rings.append([_to_xyz(axis, pos, u, v, scale, where) for u, v in points])
    vertices = [pt for section in rings for pt in section]
    faces = []
    for layer in range(len(rings) - 1):
        for j in range(width):
            a = layer * width + j
            b = layer * width + (j + 1) % width
            c = (layer + 1) * width + (j + 1) % width
            d = (layer + 1) * width + j
            # Two triangles are always planar, including tapered or twisted
            # non-coplanar quads. Shared indices preserve edge topology.
            faces.extend(((a, b, c), (a, c, d)))
    if caps:
        # CCW ring normal points along positive loft axis; cap normals must
        # point out of the volume, so reverse the first ring only.
        faces.insert(0, tuple(reversed(range(width))))
        faces.append(tuple((len(rings) - 1) * width + j
                           for j in range(width)))
    component = Component(name, vertices, faces, color, mip, uv)
    _checked_faces(component, where)
    return component


def _project_uv(vertex, options, scale, where):
    result = []
    for i, axis in enumerate(options["axes"]):
        units = Decimal(vertex[AXIS[axis]]) / scale
        uv = ((units - options["origin"][i]) * options["pixels_per_unit"][i]
              + options["offset"][i]).to_integral_value(
                  rounding=ROUND_HALF_EVEN)
        if uv < 0 or uv > 65535:
            _fail(where, f"{axis.upper()} texture coordinate {uv} exceeds 0..65535")
        result.append(int(uv))
    return result


def _make_parts(recipe):
    _keys(recipe, {"schema", "coordinate_scale", "operations", "description"},
          {"schema", "operations"}, "recipe")
    if recipe["schema"] != SCHEMA:
        _fail("recipe.schema", f"expected {SCHEMA!r}")
    scale = _integer(recipe.get("coordinate_scale", 1), "coordinate_scale", 1, 1_000_000)
    ops = recipe["operations"]
    if not isinstance(ops, list) or not 1 <= len(ops) <= MAX_OPERATIONS:
        _fail("operations", f"expected 1-{MAX_OPERATIONS} operations")
    if "description" in recipe and not isinstance(recipe["description"], str):
        _fail("description", "must be text")
    result = []
    seen = {}
    for i, value in enumerate(ops):
        where = f"operations[{i}]"
        op = _object(value, where)
        kind = op.get("type")
        name = _name(op.get("name"), where + ".name")
        if name.casefold() in seen:
            _fail(where, f"duplicate component name {name!r}")
        if kind == "loft":
            _keys(op, {"type", "name", "axis", "sections", "caps",
                       "color", "material", "uv"},
                  {"type", "name", "axis", "sections"}, where)
            axis = _axis(op["axis"], where + ".axis")
            sections = op["sections"]
            if not isinstance(sections, list) or not 2 <= len(sections) <= 128:
                _fail(where, "sections must contain 2-128 cross-sections")
            segments = []
            for j, value in enumerate(sections):
                section = _object(value, f"{where}.sections[{j}]")
                if "outline" in section:
                    _keys(section, {"at", "outline"}, {"at", "outline"},
                          f"{where}.sections[{j}]")
                    ring = section["outline"]
                else:
                    ring = _rectangle(section, f"{where}.sections[{j}]")
                segments.append((section["at"], ring))
            color, mip, uv, caps = _options(op, where)
            part = _rings(name, axis, segments, scale, color, mip, uv, caps, where)
        elif kind == "extrude":
            _keys(op, {"type", "name", "axis", "outline", "from", "to",
                       "caps", "color", "material", "uv"},
                  {"type", "name", "axis", "outline", "from", "to"}, where)
            axis = _axis(op["axis"], where + ".axis")
            color, mip, uv, caps = _options(op, where)
            part = _rings(
                name, axis, [(op["from"], op["outline"]),
                             (op["to"], op["outline"])],
                scale, color, mip, uv, caps, where)
        elif kind == "mirror":
            _keys(op, {"type", "name", "source", "axis", "at"},
                  {"type", "name", "source", "axis"}, where)
            source = op["source"]
            if source not in seen:
                _fail(where, f"source component {source!r} must precede mirror")
            axis = AXIS[_axis(op["axis"], where + ".axis")]
            plane = _raw(op.get("at", 0), scale, where + ".at")
            original = seen[source]
            points = []
            for old in original.vertices:
                p = list(old)
                reflected = 2 * plane - p[axis]
                if not INT32_MIN <= reflected <= INT32_MAX:
                    _fail(where, "reflected coordinate exceeds signed 32-bit")
                p[axis] = reflected
                points.append(tuple(p))
            # Reflection changes chirality; reverse every face to preserve
            # outward winding and consistent triangle normals.
            part = Component(name, points, [tuple(reversed(f)) for f in original.faces],
                             original.color, original.mip, original.uv, source=source)
            _checked_faces(part, where)
        else:
            _fail(where, "type must be 'loft', 'extrude', or 'mirror'")
        seen[name] = part
        result.append(part)
    total_v = sum(len(p.vertices) for p in result)
    total_f = sum(len(p.faces) for p in result)
    if total_v > MAX_VERTICES or total_f > MAX_FACES:
        _fail("recipe", f"model exceeds safety budget ({MAX_VERTICES} vertices, "
                        f"{MAX_FACES} faces)")
    return result, scale


def generate_source(recipe):
    """Generate N3 and a manifest from a validated declarative recipe.

    No filesystem writes. The returned source is compiled/validated by the
    caller before any binary or source export is committed.
    """
    recipe = _object(recipe, "recipe")
    components, scale = _make_parts(recipe)
    statements = [
        "3D VERSION 3.0;",
        "% ICR2_COORD_SCALE: 1",
        "% Generated from a declarative recipe by icr2_3do_ai Stage 2.",
        "% Components use LIST grouping; automatic Papyrus BSP authoring is not implemented.",
    ]
    roots = []
    parts = []
    for comp in components:
        statements.append(f"% COMPONENT: {comp.name}"
                          + (f" (mirrored from {comp.source})" if comp.source else ""))
        vertex_names = []
        for i, point in enumerate(comp.vertices):
            label = f"{comp.name}_v{i:04d}"
            vertex_names.append(label)
            xyz = ", ".join(str(value) for value in point)
            uv = (_project_uv(point, comp.uv, scale, f"{comp.name}.{label}")
                  if comp.uv is not None else None)
            if uv is not None:
                statements.append(
                    f"{label}: [<{xyz}>, T=<{uv[0]}, {uv[1]}>];")
            else:
                statements.append(f"{label}: [<{xyz}>];")
        face_names = []
        for i, face in enumerate(comp.faces):
            label = f"{comp.name}_p{i:04d}"
            refs = ", ".join(vertex_names[idx] for idx in face)
            opcode = "POLY [T]" if comp.mip else "POLY"
            statements.append(f"{label}: {opcode} <{comp.color}> {{{refs}}};")
            face_names.append(label)
        group = f"{comp.name}_geo"
        statements.append(f"{group}: LIST {{{', '.join(face_names)}}};")
        if comp.mip:
            material = f"{comp.name}_mat"
            statements.append(
                f'{material}: MATERIAL MIP="{comp.mip}", GROUP=3, {group};')
            roots.append(material)
        else:
            roots.append(group)
        parts.append({
            "name": comp.name, "kind": "mirror" if comp.source else "primitive",
            "mirrored_from": comp.source,
            "vertex_count": len(comp.vertices), "polygon_count": len(comp.faces),
            "material": comp.mip, "color": comp.color,
            "bounds_raw": {
                "min": [min(p[axis] for p in comp.vertices) for axis in range(3)],
                "max": [max(p[axis] for p in comp.vertices) for axis in range(3)],
            },
        })
    statements.append(f"root: LIST {{{', '.join(roots)}}};")
    source = "\n".join(statements) + "\n"
    manifest = {
        "schema": SCHEMA, "coordinate_scale": int(scale),
        "component_count": len(components),
        "vertex_count": sum(p["vertex_count"] for p in parts),
        "polygon_count": sum(p["polygon_count"] for p in parts),
        "components": parts,
        "limits": {"vertices": MAX_VERTICES, "polygons": MAX_FACES,
                   "operations": MAX_OPERATIONS},
        "caveats": [
            "LIST order is deterministic but not a generated view-dependent BSP tree.",
            "Faces use polygon vertex winding; engine-specific culling still requires in-game checks.",
            "Planar UV projection does not automatically unwrap complex surfaces or account for MIP content.",
            "Mirroring reverses face winding; UV projection is recomputed in world coordinates.",
            "Recipe units are converted to raw Papyrus units using the explicit coordinate_scale.",
        ],
    }
    return source, manifest
