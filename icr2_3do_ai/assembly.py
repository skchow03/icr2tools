"""Structured Stage 2 assembly for new N3 recipes.

This is a small source-level intermediate representation: component meshes,
named assemblies, FACE gates and render nodes are validated *before* writing
N3. No generated source is parsed or patched with regular expressions.
The existing n3_compile and three_do modules remain the only binary backend.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal

from .parametric import (
    INT32_MAX, INT32_MIN, RecipeError, _checked_faces, _fail, _integer,
    _keys, _name, _number, _object, _project_uv, _raw,
)
from .surface_checks import find_surface_conflicts


def _vector(value, scale, where):
    if not isinstance(value, list) or len(value) != 3:
        _fail(where, "expected [x, y, z] in recipe coordinate units")
    return tuple(_raw(v, scale, f"{where}[{i}]") for i, v in enumerate(value))


def _point(value, anchors, scale, where):
    if isinstance(value, list):
        return _vector(value, scale, where)
    spec = _object(value, where)
    _keys(spec, {"anchor", "offset"}, {"anchor"}, where)
    anchor = _name(spec["anchor"], where + ".anchor")
    if anchor not in anchors:
        _fail(where, f"undefined anchor {anchor!r}")
    offset = _vector(spec.get("offset", [0, 0, 0]), scale, where + ".offset")
    return _add(anchors[anchor], offset, where)


def _add(a, b, where):
    point = tuple(x + y for x, y in zip(a, b))
    if any(x < INT32_MIN or x > INT32_MAX for x in point):
        _fail(where, "coordinate exceeds signed 32-bit Papyrus range")
    return point


def _transform(value, scale, where, *, rigid=False):
    value = _object(value, where)
    permitted = {"translate", "rotate_z_quarters"}
    if not rigid:
        permitted.add("scale")
    _keys(value, permitted, set(), where)
    rotation = _integer(
        value.get("rotate_z_quarters", 0), where + ".rotate_z_quarters", 0, 3)
    factor = _number(value.get("scale", 1), where + ".scale")
    if factor <= 0:
        _fail(where, "uniform scale must be greater than zero")
    return {
        "translate": _vector(value.get("translate", [0, 0, 0]),
                             scale, where + ".translate"),
        "rotation": rotation, "scale": factor,
    }


def _apply(point, origin, transform, where):
    """Exact quarter-turns and uniform scale: never round a vertex silently."""
    dx, dy, dz = (point[i] - origin[i] for i in range(3))
    for _ in range(transform["rotation"]):
        dx, dy = -dy, dx
    delta = (dx, dy, dz)
    result = []
    for i in range(3):
        scaled = Decimal(delta[i]) * transform["scale"]
        if scaled != scaled.to_integral_value():
            _fail(where, "scaled coordinate is fractional in raw units; "
                         "increase coordinate_scale or choose an exact scale")
        result.append(origin[i] + int(scaled) + transform["translate"][i])
    return _add((0, 0, 0), tuple(result), where)


def _plane(value, scale, anchors, where):
    if not isinstance(value, list) or len(value) != 3:
        _fail(where, "plane must contain three ordered points")
    return [_point(p, anchors, scale, f"{where}[{i}]")
            for i, p in enumerate(value)]


def _normal(points, where):
    a, b, c = points
    x = tuple(b[i] - a[i] for i in range(3))
    y = tuple(c[i] - a[i] for i in range(3))
    n = (x[1]*y[2] - x[2]*y[1],
         x[2]*y[0] - x[0]*y[2],
         x[0]*y[1] - x[1]*y[0])
    if n == (0, 0, 0):
        _fail(where, "plane points are collinear or identical")
    return n


def _side(normal, origin, camera):
    return sum(normal[i] * (camera[i] - origin[i]) for i in range(3))


def _list(value, where):
    if not isinstance(value, list):
        _fail(where, "expected a list")
    return value


def _items(value, where):
    result = [_name(x, f"{where}[{i}]") for i, x in
              enumerate(_list(value, where))]
    if not result or len(result) != len(set(result)):
        _fail(where, "members must be nonempty and unique")
    return result


def assemble_source(components, scale, config, surface_policy):
    """Render structured assembly as N3 and return a Stage 2 manifest.

    Every drawable component and external reference must occur exactly once in
    the root graph. This prevents invisible parts and duplicate overpainting.
    """
    config = _object(config, "recipe.assembly")
    _keys(config,
          {"coordinate_system", "game_transform", "anchors", "externals",
           "groups", "gates", "nodes", "root"},
          {"coordinate_system"}, "recipe.assembly")
    frame = config["coordinate_system"]
    if frame not in ("source", "game"):
        _fail("assembly.coordinate_system", "use 'source' or 'game'")
    if frame == "game" and "game_transform" in config:
        _fail("assembly.game_transform",
              "game coordinates are already final; do not transform twice")
    global_tf = _transform(config.get("game_transform", {}), scale,
                           "assembly.game_transform", rigid=True)
    identity = _transform({}, scale, "assembly.identity")
    known = {p.name: p for p in components}
    component_names = set(known)

    anchors = {}
    for i, entry in enumerate(_list(config.get("anchors", []), "assembly.anchors")):
        where = f"assembly.anchors[{i}]"
        entry = _object(entry, where)
        _keys(entry, {"name", "at"}, {"name", "at"}, where)
        name = _name(entry["name"], where + ".name")
        if name in anchors:
            _fail(where, f"duplicate anchor {name!r}")
        anchors[name] = _vector(entry["at"], scale, where + ".at")

    externals = {}
    for i, entry in enumerate(_list(config.get("externals", []), "assembly.externals")):
        where = f"assembly.externals[{i}]"
        entry = _object(entry, where)
        _keys(entry, {"name", "model", "at", "rotation_tenths"},
              {"name", "model", "at"}, where)
        name = _name(entry["name"], where + ".name")
        model = entry["model"]
        if (not isinstance(model, str) or not 1 <= len(model) <= 8 or
                not all(c.isascii() and (c.isalnum() or c == "_") for c in model)):
            _fail(where + ".model",
                  "EXTERN name must be 1-8 ASCII letters/digits/underscore, without .3do")
        if name in externals or name in component_names:
            _fail(where, f"duplicate object name {name!r}")
        angles = entry.get("rotation_tenths", [0, 0, 0])
        if not isinstance(angles, list) or len(angles) != 3:
            _fail(where + ".rotation_tenths", "expected three N3 angles in tenths of a degree")
        rotation = tuple(_integer(v, where + ".rotation_tenths", -3600, 3600)
                         for v in angles)
        externals[name] = {
            "name": name, "model": model.upper(),
            "at": _point(entry["at"], anchors, scale, where + ".at"),
            "rotation": rotation,
        }

    all_parts = component_names | set(externals)
    groups = {}
    ownership = {}
    for i, entry in enumerate(_list(config.get("groups", []), "assembly.groups")):
        where = f"assembly.groups[{i}]"
        entry = _object(entry, where)
        _keys(entry, {"name", "members", "anchor", "transform"},
              {"name", "members", "anchor"}, where)
        name = _name(entry["name"], where + ".name")
        if name in all_parts or name in groups:
            _fail(where, f"duplicate group name {name!r}")
        members = _items(entry["members"], where + ".members")
        anchor = _name(entry["anchor"], where + ".anchor")
        if anchor not in anchors:
            _fail(where, f"undefined pivot anchor {anchor!r}")
        for member in members:
            if member not in all_parts:
                _fail(where, f"unknown component or external {member!r}")
            if member in ownership:
                _fail(where, f"{member!r} already belongs to {ownership[member]!r}")
            ownership[member] = name
        groups[name] = {
            "name": name, "anchor": anchor, "members": members,
            "transform": _transform(entry.get("transform", {}), scale,
                                    where + ".transform"),
        }

    # External 3DO geometry is linked, not rescaled by the parent. Moving an
    # attachment center is not equivalent to scaling the child mesh/sprite.
    for group in groups.values():
        if group["transform"]["scale"] != 1 and any(
                member in externals for member in group["members"]):
            _fail("assembly.groups", "cannot scale an assembly containing "
                 "EXTERN references; scale its native mesh separately")

    # A single transform applies to meshes and DYNAMIC anchors together.
    # Seatbacks can intentionally remain outside a driver assembly.
    def local_tf(member):
        group = groups.get(ownership.get(member))
        if group is None:
            return (0, 0, 0), identity
        return anchors[group["anchor"]], group["transform"]

    def position(point, member, where):
        origin, transform = local_tf(member)
        local = _apply(point, origin, transform, where)
        return _apply(local, (0, 0, 0), global_tf, where + ".game")

    for comp in components:
        comp.vertices = [position(p, comp.name, f"{comp.name}.v{i}")
                         for i, p in enumerate(comp.vertices)]
        _checked_faces(comp, "assembly." + comp.name)

    for ext in externals.values():
        ext["at"] = position(ext["at"], ext["name"], "external." + ext["name"])
        group_name = ownership.get(ext["name"])
        local_rotation = groups[group_name]["transform"]["rotation"] if group_name else 0
        # The first N3 rotation field is heading, in 0.1 degree increments.
        # Only Z yaw is supported for groups containing DYNAMIC objects.
        ext["rotation"] = (
            ext["rotation"][0] + 900*(local_rotation + global_tf["rotation"]),
            ext["rotation"][1], ext["rotation"][2],
        )

    gates = {}
    used_gated_faces = set()
    for i, entry in enumerate(_list(config.get("gates", []), "assembly.gates")):
        where = f"assembly.gates[{i}]"
        entry = _object(entry, where)
        _keys(entry, {"name", "component", "faces", "plane",
                      "visible_from", "hidden_from"},
              {"name", "component", "faces", "plane",
               "visible_from", "hidden_from"}, where)
        name = _name(entry["name"], where + ".name")
        target = _name(entry["component"], where + ".component")
        if name in gates or name in all_parts or name in groups:
            _fail(where, "duplicate or reserved gate name")
        if target not in known:
            _fail(where, f"gate targets unknown component {target!r}")
        indices = _list(entry["faces"], where + ".faces")
        if not indices:
            _fail(where, "gate requires at least one polygon index")
        indices = [_integer(v, where + ".faces", 0,
                            len(known[target].faces)-1) for v in indices]
        if len(indices) != len(set(indices)):
            _fail(where, "duplicate gated polygon index")
        for face_index in indices:
            key = (target, face_index)
            if key in used_gated_faces:
                _fail(where, "polygon already assigned a FACE gate")
            used_gated_faces.add(key)
        plane = [position(p, target, where + ".plane")
                 for p in _plane(entry["plane"], scale, anchors, where + ".plane")]
        visible = position(_point(entry["visible_from"], anchors, scale,
                                  where + ".visible_from"), target, where + ".visible_from")
        hidden = position(_point(entry["hidden_from"], anchors, scale,
                                 where + ".hidden_from"), target, where + ".hidden_from")
        normal = _normal(plane, where + ".plane")
        if _side(normal, plane[0], visible) <= 0 or _side(normal, plane[0], hidden) >= 0:
            _fail(where, "visible_from must lie on positive FACE halfspace and "
                         "hidden_from on negative halfspace (neither on plane)")
        gates[name] = {"component": target, "faces": indices,
                       "plane": plane, "visible_from": visible,
                       "hidden_from": hidden}

    nodes = {}
    for i, entry in enumerate(_list(config.get("nodes", []), "assembly.nodes")):
        where = f"assembly.nodes[{i}]"
        entry = _object(entry, where)
        kind = entry.get("kind")
        if kind not in ("list", "bspa", "bspn"):
            _fail(where + ".kind", "expected 'list', 'bspa', or 'bspn'")
        needed = {"name", "kind", "children"}
        allowed = needed | ({"plane"} if kind != "list" else set())
        _keys(entry, allowed, needed | ({"plane"} if kind != "list" else set()), where)
        name = _name(entry["name"], where + ".name")
        if name in all_parts or name in groups or name in nodes or name in gates:
            _fail(where, f"duplicate painter node name {name!r}")
        children = _items(entry["children"], where + ".children")
        expected = {"list": None, "bspa": 3, "bspn": 2}[kind]
        if expected is not None and len(children) != expected:
            _fail(where, f"{kind.upper()} requires exactly {expected} children")
        node = {"name": name, "kind": kind, "children": children}
        if kind != "list":
            node["plane"] = [
                _apply(p, (0, 0, 0), global_tf, where + ".game")
                for p in _plane(entry["plane"], scale, anchors, where + ".plane")
            ]
            _normal(node["plane"], where + ".plane")
        nodes[name] = node

    # Resolve a typed acyclic render graph, rejecting double-drawn and missing
    # objects. Transform groups are N3 LIST nodes, not opaque source strings.
    render_refs = {**{k: "component" for k in known},
                   **{k: "external" for k in externals},
                   **{k: "group" for k in groups},
                   **{k: "node" for k in nodes}}
    if "root" in config:
        root_children = [_name(config["root"], "assembly.root")]
    elif nodes:
        _fail("assembly.root", "explicit painter nodes require an explicit root")
    else:
        root_children = list(groups) + [
            name for name in list(known) + list(externals) if name not in ownership
        ]
    visits = Counter()
    visited_nodes = set()
    def walk(name, stack):
        if name not in render_refs:
            _fail("assembly.root", f"unknown render object {name!r}")
        if name in stack:
            _fail("assembly.root", f"cycle in painter graph at {name!r}")
        kind = render_refs[name]
        if kind in ("component", "external"):
            visits[name] += 1
        else:
            if name in visited_nodes:
                _fail("assembly.root", f"group or painter node {name!r} drawn twice")
            visited_nodes.add(name)
            children = groups[name]["members"] if kind == "group" else nodes[name]["children"]
            for child in children:
                walk(child, stack | {name})
    for child in root_children:
        walk(child, set())
    if set(visits) != all_parts or any(count != 1 for count in visits.values()):
        _fail("assembly.root", "every component and external must be drawn exactly "
                             "once; missing or duplicated: " +
              ", ".join(sorted(name for name in all_parts
                               if visits[name] != 1)))
    if set(groups) - visited_nodes or set(nodes) - visited_nodes:
        _fail("assembly.root", "unused group or painter node: " +
              ", ".join(sorted((set(groups)|set(nodes))-visited_nodes)))

    if surface_policy not in ("warn", "error", "off"):
        _fail("recipe.surface_checks", "expected 'warn', 'error', or 'off'")
    diagnostics = (find_surface_conflicts(components)
                   if surface_policy != "off" else [])
    if surface_policy == "error" and diagnostics:
        first = diagnostics[0]
        _fail("recipe.surface_checks",
              f"{first['code']}: {first.get('components', [])}; "
              "overlapping surfaces require explicit review")

    lines = [
        "3D VERSION 3.0;",
        "% ICR2_COORD_SCALE: 1",
        "% Stage 2 structured assembly; source and game frames are explicit.",
        "% FACE halfspaces and BSP paint order require in-game camera verification.",
    ]
    symbols = set()
    def emit(name, definition):
        if name in symbols or name == "root":
            _fail("assembly", f"N3 symbol collision at {name!r}")
        symbols.add(name)
        lines.append(f"{name}: {definition};")
    def vertex(name, point, uv=None):
        coords = ", ".join(map(str, point))
        tex = f", T=<{uv[0]}, {uv[1]}>" if uv is not None else ""
        emit(name, f"[<{coords}>{tex}]")
    def plane_points(name, points):
        labels = []
        for suffix, point in zip(("a", "b", "c"), points):
            label = f"{name}_{suffix}"
            vertex(label, point)
            labels.append(label)
        return "(" + ", ".join(labels) + ")"
    def render_name(name):
        if name in known:
            part = known[name]
            return name + ("_mat" if part.mip else "_geo")
        return name

    gated = {}
    for name, gate in gates.items():
        for index in gate["faces"]:
            gated[(gate["component"], index)] = name + f"_p{index:04d}"

    parts = []
    for comp in components:
        lines.append(f"% COMPONENT: {comp.name}")
        vertices = []
        for index, point in enumerate(comp.vertices):
            label = f"{comp.name}_v{index:04d}"
            uv = (_project_uv(point, comp.uv, scale, comp.name + "." + label)
                  if comp.uv is not None else None)
            vertex(label, point, uv)
            vertices.append(label)
        polygon_labels = []
        for index, face in enumerate(comp.faces):
            label = f"{comp.name}_p{index:04d}"
            opcode = "POLY [T]" if comp.mip else "POLY"
            emit(label, f"{opcode} <{comp.color}> " +
                 "{" + ", ".join(vertices[j] for j in face) + "}")
            polygon_labels.append(gated.get((comp.name, index), label))
        emit(comp.name + "_geo", "LIST {" + ", ".join(polygon_labels) + "}")
        if comp.mip:
            emit(comp.name + "_mat",
                 f'MATERIAL MIP="{comp.mip}", GROUP=3, {comp.name}_geo')
        parts.append({
            "name": comp.name, "kind": "mirror" if comp.source else "primitive",
            "mirrored_from": comp.source, "vertex_count": len(comp.vertices),
            "polygon_count": len(comp.faces), "material": comp.mip,
            "color": comp.color,
            "bounds_raw": {
                "min": [min(p[axis] for p in comp.vertices) for axis in range(3)],
                "max": [max(p[axis] for p in comp.vertices) for axis in range(3)],
            },
        })

    for name, gate in gates.items():
        plane = plane_points(name, gate["plane"])
        for index in gate["faces"]:
            emit(name + f"_p{index:04d}",
                 f"FACE {plane}, {gate['component']}_p{index:04d}")

    for ext in externals.values():
        x, y, z = ext["at"]
        h, p, r = ext["rotation"]
        emit(ext["name"],
             f'DYNAMIC {x}, {y}, {z}, {h}, {p}, {r}, 1, EXTERN "{ext["model"]}"')

    for group in groups.values():
        emit(group["name"], "LIST {" +
             ", ".join(render_name(x) for x in group["members"]) + "}")
    for node in nodes.values():
        refs = ", ".join(render_name(x) for x in node["children"])
        if node["kind"] == "list":
            emit(node["name"], "LIST {" + refs + "}")
        else:
            plane = plane_points(node["name"], node["plane"])
            emit(node["name"], node["kind"].upper() + " " + plane + ", " + refs)
    lines.append("root: LIST {" + ", ".join(render_name(x) for x in root_children) + "};")
    source = "\n".join(lines) + "\n"

    manifest = {
        "schema": "icr2.n3.recipe.v1",
        "coordinate_scale": int(scale),
        "component_count": len(components),
        "vertex_count": sum(x["vertex_count"] for x in parts),
        "polygon_count": sum(x["polygon_count"] for x in parts),
        "components": parts,
        "surface_checks": {
            "policy": surface_policy, "diagnostics": diagnostics,
            "counts": dict(sorted(Counter(x["code"] for x in diagnostics).items())),
        },
        "assembly": {
            "coordinate_system": frame,
            "game_transform": {
                "rotate_z_quarters": global_tf["rotation"],
                "translate_raw": list(global_tf["translate"]),
            },
            "anchors_source_raw": {k: list(v) for k, v in anchors.items()},
            "anchors_game_raw": {
                k: list(_apply(v, (0,0,0), global_tf, "anchors_game"))
                for k, v in anchors.items()
            },
            "groups": [
                {"name": g["name"], "anchor": g["anchor"],
                 "members": g["members"],
                 "rotate_z_quarters": g["transform"]["rotation"],
                 "translate_raw": list(g["transform"]["translate"]),
                 "scale": str(g["transform"]["scale"])}
                for g in groups.values()
            ],
            "externals": [
                {"name": e["name"], "model": e["model"],
                 "filename": e["model"] + ".3do",
                 "at_game_raw": list(e["at"]),
                 "rotation_tenths": list(e["rotation"])}
                for e in externals.values()
            ],
            "gates": [
                {"name": k, "component": g["component"], "faces": g["faces"],
                 "plane_game_raw": [list(p) for p in g["plane"]],
                 "positive_camera_game_raw": list(g["visible_from"]),
                 "negative_camera_game_raw": list(g["hidden_from"])}
                for k, g in gates.items()
            ],
            "nodes": [{"name": n["name"], "kind": n["kind"],
                       "children": n["children"],
                       **({"plane_game_raw": [list(p) for p in n["plane"]]}
                          if "plane" in n else {})}
                      for n in nodes.values()],
            "root": root_children,
        },
        "limits": {"vertices": 30000, "polygons": 60000, "operations": 128},
        "caveats": [
            "FACE halfspace cameras verify oriented geometry, not runtime visibility.",
            "BSPA/BSPN express painter sorting; the game renderer is not simulated.",
            "EXTERN dependencies are recorded but external file validation is optional.",
            "Uniform scaling must yield integer raw units; only 90-degree Z turns are supported.",
            "Painter ordering cannot repair intersecting or redundant surfaces.",
        ],
    }
    return source, manifest
