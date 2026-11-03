"""Resolve N3 source declarations to GPU inspection targets.

Cursor inspection is deliberately read-only.  It never recompiles the N3,
reorders BSP indices, edits binary files or changes renderer resource lookup.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import re

import numpy as np


_DECLARATION = re.compile(r"^[ \t]*([A-Za-z_][A-Za-z_0-9-]*)[ \t]*:[ \t]*(.*)$")
_POLYGON = re.compile(r"^POLY(?:\s+\[T\])?\s*<", re.I | re.S)
_VERTEX = re.compile(r"^\[\s*<", re.S)
_BINARY_LABEL = re.compile(r"^_(\d+)$")


@dataclass(frozen=True)
class SourceTarget:
    first_line: int  # zero-based QTextBlock number
    last_line: int
    kind: str         # "polygon" or "vertex"
    label: str


@dataclass(frozen=True)
class SourceTargetIndex:
    """Index complete declarations once, then answer cursor moves in O(log n)."""

    targets: tuple[SourceTarget, ...]
    starts: tuple[int, ...]

    def at_line(self, line: int) -> tuple[str, str] | None:
        pos = bisect_right(self.starts, line) - 1
        if pos < 0:
            return None
        target = self.targets[pos]
        if line > target.last_line:
            return None
        return target.kind, target.label


def _without_comment(line: str) -> str:
    quoted = False
    for i, ch in enumerate(line):
        if ch == '"':
            quoted = not quoted
        elif ch == '%' and not quoted:
            return line[:i]
    return line


def index_source_targets(source: str) -> SourceTargetIndex:
    """Identify complete, possibly multiline POLY and vertex declarations.

    Comments and unrelated N3 constructs are not inspection targets.
    Partially typed declarations are omitted until source validates.
    """
    lines = source.splitlines()
    targets = []
    index = 0
    while index < len(lines):
        start = index
        match = _DECLARATION.match(_without_comment(lines[index]))
        if match is None:
            index += 1
            continue
        label = match.group(1)
        command = [match.group(2)]
        while ';' not in command[-1] and index + 1 < len(lines):
            next_code = _without_comment(lines[index + 1])
            if _DECLARATION.match(next_code):
                break
            index += 1
            command.append(next_code)
        code = "\n".join(command).lstrip()
        if ';' in code:
            if _POLYGON.match(code):
                targets.append(SourceTarget(start, index, "polygon", label))
            elif _VERTEX.match(code):
                targets.append(SourceTarget(start, index, "vertex", label))
        index += 1
    return SourceTargetIndex(tuple(targets),
                             tuple(target.first_line for target in targets))


def target_offset(model, kind: str, label: str) -> int | None:
    """Resolve authored N3 labels or generated _offset labels into this model.

    The N3 compiler records its *compiled* offsets, which can differ from
    original % ICR2_OFFSET annotations after any source rebuild.
    """
    if model is None:
        return None
    mapping = getattr(model, "n3_label_offsets", {})
    offset = mapping.get(label)
    if offset is None:
        match = _BINARY_LABEL.fullmatch(label)
        if match:
            offset = int(match.group(1))
    if kind == "polygon" and offset in model.polygons:
        return offset
    if kind == "vertex" and offset in model.vertices:
        return offset
    return None


def polygon_mesh_range(scene, mesh, offset: int | None):
    """Find a root-model polygon in the flattened GPU buffer."""
    if scene is None or mesh is None or offset is None:
        return None
    polygon = scene.polygon_lookup.get((0, offset))
    return mesh.polygon_ranges.get(polygon)


def vertex_screen_position(model, mesh, offset, matrix, width, height):
    """Project a source vertex to logical viewport pixels, or None if clipped.

    Model XYZ are in raw Papyrus units; GPU XYZ use the mesh centre/scale.
    """
    if model is None or mesh is None or offset not in model.vertices:
        return None
    raw = np.asarray(model.vertices[offset].xyz, dtype=np.float64)
    center = np.asarray(mesh.center, dtype=np.float64)
    scale = float(mesh.scale)
    if not np.isfinite(raw).all() or not np.isfinite(scale) or scale <= 0:
        return None
    local = (raw - center) / scale
    point = np.array([*local, 1.0], dtype=np.float64)
    clip = np.asarray(matrix, dtype=np.float64) @ point
    if not np.isfinite(clip).all() or clip[3] <= 0:
        return None
    if np.any(np.abs(clip[:3]) > clip[3]):
        return None
    ndc = clip[:2] / clip[3]
    return (float(width * (ndc[0] + 1.0) / 2.0),
            float(height * (1.0 - ndc[1]) / 2.0))
