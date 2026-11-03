"""Active N3 declarations selected by SWITCH DISTANCE (RES) traversal.

This deliberately evaluates distance/LOD, not camera-facing BSP culling or
per-pixel occlusion. It preserves parent wrappers, switch nodes and geometry
dependencies so a filtered .3D document remains meaningful to edit.
"""
from __future__ import annotations

import math
import re

from gpu_viewer.source_filters import index_source_entries

_LABEL = re.compile(r"^[ \t]*([A-Za-z_][A-Za-z_0-9-]*)\s*:")
_PLANE = re.compile(
    r"\b(?:FACE2?|BSPF|BSPA|BSP2|BSPN)\s*\(([^)]*)\)", re.I | re.S)
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9-]*\Z")


def entry_is_active(entry, names):
    """A source declaration participates only if its current name is active."""
    match = _LABEL.match(entry.preview)
    return bool(match and match.group(1) in names)



def label_offsets(model):
    """Map current compiled names and exported binary _offset aliases."""
    if model is None:
        return {}
    mapping = dict(getattr(model, "n3_label_offsets", {}))
    for offset in model.records:
        mapping.setdefault(f"_{offset}", offset)
    for offset in model.vertices:
        mapping.setdefault(f"_{offset}", offset)
    return mapping


def plane_vertex_dependencies(source, model, entries=None):
    """Retain named plane-defining vertices in FACE/BSP source declarations.

    A compiled 3DO stores a plane equation, not the source's three vertex
    pointers. Recover those only from the source when available. Quoted
    paths and numeric plane coefficients never count as vertices.
    """
    if model is None:
        return {}
    mapping = label_offsets(model)
    lines = source.splitlines()
    dependencies = {}
    for entry in entries if entries is not None else index_source_entries(source):
        if entry.category not in ("FACE", "BSP"):
            continue
        statement = "\n".join(lines[entry.first_line:entry.last_line + 1])
        match = _LABEL.match(statement)
        if match is None:
            continue
        offset = mapping.get(match.group(1))
        if offset not in model.planes:
            continue
        plane = _PLANE.search(statement)
        if plane is None:
            continue
        refs = [term.strip() for term in plane.group(1).split(",")]
        if len(refs) != 3 or not all(_IDENTIFIER.fullmatch(x) for x in refs):
            continue
        vertices = {mapping.get(label) for label in refs}
        dependencies[offset] = vertices & model.vertices.keys()
    return dependencies


def active_source_labels(model, distance, camera, plane_dependencies=None):
    """All named records/vertices reachable through the current RES choices.

    distance is None (all branches), "auto" (per-anchor 3D eye distance),
    or a manual raw-unit distance. BSP and FACE children are traversed on
    both sides: this answers which LOD branch, not pixel visibility.
    """
    if model is None:
        return set()
    plane_dependencies = plane_dependencies or {}
    active = set()
    visited = set()
    pending = [(model.root_offset, True)]
    while pending:
        offset, is_root = pending.pop()
        if offset < 0 or (offset == 0 and not is_root) or offset in visited:
            continue
        visited.add(offset)
        if offset not in model.records:
            continue
        active.add(offset)
        polygon = model.polygons.get(offset)
        if polygon is not None:
            active.update(v for v in polygon.refs
                          if v in model.vertices)
        if offset in model.switches:
            switch = model.switches[offset]
            if switch.anchor in model.vertices:
                active.add(switch.anchor)
            if distance is None:
                pending.extend((pointer, False) for _, pointer in switch.branches)
            else:
                if distance == "auto":
                    anchor = model.vertices.get(switch.anchor)
                    if anchor is None:
                        # Do not guess; the compiler normally validates this.
                        continue
                    chosen_distance = math.dist(camera, anchor.xyz)
                else:
                    chosen_distance = distance
                choice = switch.choose(chosen_distance)
                if choice is not None:
                    pending.append((choice[1], False))
            continue
        sprite = model.pmp_sprites.get(offset)
        if sprite is not None and sprite.vertex_ref in model.vertices:
            active.add(sprite.vertex_ref)
        active.update(plane_dependencies.get(offset, ()))
        pending.extend((pointer, False) for pointer in model.children.get(offset, ()))
    return {name for name, offset in label_offsets(model).items()
            if offset in active}
