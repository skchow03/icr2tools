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

    def target_at_line(self, line: int) -> SourceTarget | None:
        pos = bisect_right(self.starts, line) - 1
        if pos < 0:
            return None
        target = self.targets[pos]
        return target if line <= target.last_line else None

    def at_line(self, line: int) -> tuple[str, str] | None:
        target = self.target_at_line(line)
        return (target.kind, target.label) if target is not None else None


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



def polygon_inspection_notice(model, offset, visible_offsets, distance,
                              camera, render_mode):
    """Why a source POLY is not selected by the active BSP/RES traversal.

    Do not claim pixel visibility: the BSP selection may still be covered
    by another polygon.  In all-polygons mode no BSP/LOD exclusion applies.
    """
    if (model is None or offset not in model.polygons or
            render_mode == "all" or offset in visible_offsets):
        return None
    candidates, _, _ = model.switched_polygons(distance, camera, "off")
    if offset in candidates:
        return "POLY not drawn: excluded by BSP at this camera view"
    if distance is not None:
        branches, _, _ = model.switched_polygons(None, camera, "off")
        if offset in branches:
            label = ("automatic camera distance" if distance == "auto"
                     else f"distance {int(distance):,}")
            return f"POLY not drawn: inactive SWITCH DISTANCE branch ({label})"
    return "POLY not drawn: not referenced by the current scene"


@dataclass(frozen=True)
class VertexPicker:
    """Cache the current root N3 model's vertices for projected click picking.

    Child DYNAMIC geometry is deliberately not eligible: the .3D Source pane
    edits only the root model, so those vertices have no source declaration to
    navigate to. Rebuild after model recompilation, not on camera movement.
    """
    offsets: np.ndarray
    normalized: np.ndarray

    @classmethod
    def from_model(cls, model, mesh):
        if model is None or mesh is None or not model.vertices:
            return cls(np.empty(0, dtype=np.int64),
                       np.empty((0, 3), dtype=np.float64))
        offsets = np.asarray(list(model.vertices), dtype=np.int64)
        coords = np.asarray(
            [vertex.xyz for vertex in model.vertices.values()], dtype=np.float64)
        return cls(offsets, (coords - np.asarray(mesh.center, dtype=np.float64))
                   / float(mesh.scale))

    def nearest(self, matrix, x, y, width, height, *, radius=24.0,
                eligible_offsets=None):
        """Nearest projected vertex within radius in logical viewport pixels.

        Reject points outside the clip volume or behind the near plane.
        When several vertices overlap in screen space, prefer the frontmost
        depth. No OpenGL readback or GPU state is required.
        """
        if not len(self.offsets) or width <= 0 or height <= 0:
            return None
        vertices = np.column_stack((
            self.normalized, np.ones(len(self.offsets), dtype=np.float64)))
        projected = vertices @ np.asarray(matrix, dtype=np.float64).T
        w = projected[:, 3]
        valid = (np.isfinite(projected).all(axis=1) & (w > 0)
                 & (np.abs(projected[:, :3]) <= w[:, None]).all(axis=1))
        if eligible_offsets is not None:
            valid &= np.isin(self.offsets, np.fromiter(
                eligible_offsets, dtype=np.int64))
        if not valid.any():
            return None
        selected = projected[valid]
        ndc = selected[:, :3] / selected[:, 3, None]
        sx = (ndc[:, 0] + 1.0) * (width * 0.5)
        sy = (1.0 - ndc[:, 1]) * (height * 0.5)
        distance2 = (sx - x)**2 + (sy - y)**2
        nearest_distance = np.min(distance2)
        if not np.isfinite(nearest_distance) or nearest_distance > radius**2:
            return None
        candidates = np.flatnonzero(
            np.isclose(distance2, nearest_distance, atol=1e-8, rtol=0))
        # NDC depth increases with distance for both supported projections.
        winner = candidates[np.argmin(ndc[candidates, 2])]
        return int(self.offsets[valid][winner])


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
