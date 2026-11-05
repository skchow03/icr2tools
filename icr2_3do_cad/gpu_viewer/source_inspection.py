"""Resolve N3 source declarations to GPU inspection targets.

Cursor inspection is deliberately read-only.  It never recompiles the N3,
reorders BSP indices, edits binary files or changes renderer resource lookup.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import re
import struct

import numpy as np


_DECLARATION = re.compile(r"^[ \t]*([A-Za-z_][A-Za-z_0-9-]*)[ \t]*:[ \t]*(.*)$")
_POLYGON = re.compile(r"^POLY(?:\s+\[T\])?\s*<", re.I | re.S)
_VERTEX = re.compile(r"^\[\s*<", re.S)
_BINARY_LABEL = re.compile(r"^_(\d+)$")
_BSP_PLANE = re.compile(
    r"^(?:BSPF|BSPA|BSP2|BSPN)\s*\(([^)]*)\)", re.I | re.S)
_PLANE_LABEL = re.compile(r"^[A-Za-z_][A-Za-z_0-9-]*$")
_INLINE_COORDS = re.compile(
    r"^\[\s*<\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))\s*,\s*"
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+))\s*,\s*"
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+))\s*>"
    r"(?:\s*,\s*[Tt]\s*=\s*<[^>]+>)?\s*\]$", re.S)


@dataclass(frozen=True)
class SourceTarget:
    first_line: int  # zero-based QTextBlock number
    last_line: int
    kind: str         # "polygon", "vertex" or "bsp"
    label: str
    plane_operands: tuple[str, str, str] | None = None


@dataclass(frozen=True)
class SourceTargetIndex:
    """Index complete declarations once, then answer cursor moves in O(log n)."""

    targets: tuple[SourceTarget, ...]
    starts: tuple[int, ...]
    vertex_labels: frozenset[str] = frozenset()

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


def _bsp_plane_operands(code: str) -> tuple[str, str, str] | None:
    """Extract an authored plane's three vertices, not its BSP child nodes.

    Bracketed inline [<X,Y,Z>] operands contain commas. Tokenize commas only
    at the plane's top level; a five-integer coefficient tuple is *not*
    a three-vertex winding and has no overlay.
    """
    match = _BSP_PLANE.match(code)
    if match is None:
        return None
    tokens = []
    depth = 0
    start = 0
    inside = match.group(1)
    for i, char in enumerate(inside):
        if char in "[<":
            depth += 1
        elif char in "]>":
            depth -= 1
            if depth < 0:
                return None
        elif char == "," and depth == 0:
            tokens.append(inside[start:i].strip())
            start = i + 1
    if depth != 0:
        return None
    tokens.append(inside[start:].strip())
    if len(tokens) != 3 or not all(
            _PLANE_LABEL.fullmatch(token) or _INLINE_COORDS.fullmatch(token)
            for token in tokens):
        return None
    return tuple(tokens)


def index_source_targets(source: str) -> SourceTargetIndex:
    """Identify complete, possibly multiline POLY, vertex and BSP declarations.

    Comments and unrelated N3 constructs are not inspection targets.
    Partially typed declarations are omitted until source validates.
    """
    lines = source.splitlines()
    targets = []
    vertex_labels = set()
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
                vertex_labels.add(label)
            else:
                operands = _bsp_plane_operands(code)
                if operands is not None:
                    targets.append(SourceTarget(
                        start, index, "bsp", label, operands))
        index += 1
    return SourceTargetIndex(tuple(targets),
                             tuple(target.first_line for target in targets),
                             frozenset(vertex_labels))


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
    if kind == "bsp" and offset in model.planes:
        return offset
    return None


def bsp_plane_points(index: SourceTargetIndex, model, line: int):
    """Resolve three ordered BSP tuple points to compiled raw Papyrus XYZ.

    The binary contains a plane equation, *not* the authored three source
    operands. For named vertices, read the compiled coordinates at each
    declaration's mapped offset, including plane-only vertices absent from
    Model.vertices. For inline coordinates, use the compiler's exact scale.
    Never infer winding from polygon triangulation or a plane normal.
    """
    target = index.target_at_line(line)
    if (model is None or target is None or target.kind != "bsp" or
            target.plane_operands is None or
            target_offset(model, "bsp", target.label) is None):
        return None
    points = []
    scale = Decimal(str(getattr(model, "n3_coordinate_scale", 1)))
    for operand in target.plane_operands:
        if _PLANE_LABEL.fullmatch(operand):
            if operand not in index.vertex_labels:
                return None
            offset = target_offset(model, "vertex", operand)
            if offset is None:
                # Plane-only vertex declarations are valid N3 but the
                # 3DO parser indexes only renderable polygon/RES vertices.
                # Authored labels still map to compiled vertex bytes.
                mapping = getattr(model, "n3_label_offsets", {})
                offset = mapping.get(operand)
                if offset is None:
                    binary = _BINARY_LABEL.fullmatch(operand)
                    if binary:
                        offset = int(binary.group(1))
            if (offset is None or offset < 0 or
                    offset + 16 > len(getattr(model, "body", b""))):
                return None
            xyz = struct.unpack_from("<3i", model.body, offset + 4)
        else:
            coords = _INLINE_COORDS.fullmatch(operand)
            if coords is None:
                return None
            try:
                xyz = tuple(int((Decimal(value) * scale).to_integral_value(
                    rounding=ROUND_HALF_EVEN)) for value in coords.groups())
            except (InvalidOperation, OverflowError, ValueError):
                return None
        points.append(tuple(xyz))
    return tuple(points)


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


@dataclass(frozen=True)
class PolygonPicker:
    """CPU ray picker for rendered triangles belonging to the root .3D file.

    Reuse GPU mesh triangulation, so concave POLYs and FACE2-derived faces use
    exactly the same triangles as the viewport. Child instances have separate
    source files and are intentionally not selection targets. No GL readback.
    """

    mesh: object
    triangle_starts: np.ndarray
    source_offsets: np.ndarray

    @classmethod
    def from_scene(cls, scene, mesh):
        starts = []
        offsets = []
        if scene is not None and mesh is not None:
            for (instance_id, source_offset), mesh_offset in scene.polygon_lookup.items():
                if instance_id != 0:
                    continue
                span = mesh.polygon_ranges.get(mesh_offset)
                if span is None:
                    continue
                first, count = span
                starts.extend(range(first, first + count, 3))
                offsets.extend([source_offset] * (count // 3))
        return cls(mesh, np.asarray(starts, dtype=np.int64),
                   np.asarray(offsets, dtype=np.int64))

    def nearest(self, matrix, x, y, width, height, *, eligible_offsets=None):
        """Return the frontmost intersected root POLY in logical screen pixels.

        A ray through the OpenGL near/far clip planes avoids false hits on
        projected triangles behind the camera, including perspective views.
        Both sides of a face may be picked, matching disabled GL backface
        culling. Candidate triangles respect the active BSP/RES selection.
        """
        if (self.mesh is None or not len(self.triangle_starts) or
                width <= 0 or height <= 0 or
                not (0 <= x < width and 0 <= y < height)):
            return None
        starts = self.triangle_starts
        offsets = self.source_offsets
        if eligible_offsets is not None:
            allowed = np.fromiter(eligible_offsets, dtype=np.int64)
            if not allowed.size:
                return None
            mask = np.isin(offsets, allowed)
            if not mask.any():
                return None
            starts, offsets = starts[mask], offsets[mask]

        try:
            inverse = np.linalg.inv(np.asarray(matrix, dtype=np.float64))
        except np.linalg.LinAlgError:
            return None
        ndc_x = 2.0 * x / width - 1.0
        ndc_y = 1.0 - 2.0 * y / height
        near = inverse @ np.array((ndc_x, ndc_y, -1.0, 1.0))
        far = inverse @ np.array((ndc_x, ndc_y, 1.0, 1.0))
        if (not np.isfinite(near).all() or not np.isfinite(far).all()
                or abs(near[3]) < 1e-12 or abs(far[3]) < 1e-12):
            return None
        origin = near[:3] / near[3]
        ray = far[:3] / far[3] - origin
        max_distance = float(np.linalg.norm(ray))
        if not np.isfinite(max_distance) or max_distance <= 0:
            return None
        direction = ray / max_distance

        triangles = np.asarray(self.mesh.vertices, dtype=np.float64)[
            starts[:, None] + np.arange(3), :3]
        edge_a = triangles[:, 1] - triangles[:, 0]
        edge_b = triangles[:, 2] - triangles[:, 0]
        p = np.cross(direction, edge_b)
        determinant = np.einsum('ij,ij->i', edge_a, p)
        epsilon = 1e-10
        inv_determinant = np.zeros_like(determinant)
        np.divide(1.0, determinant, out=inv_determinant,
                  where=np.abs(determinant) > epsilon)
        start_to_ray = origin - triangles[:, 0]
        u = np.einsum('ij,ij->i', start_to_ray, p) * inv_determinant
        q = np.cross(start_to_ray, edge_a)
        v = q @ direction * inv_determinant
        distance = np.einsum('ij,ij->i', edge_b, q) * inv_determinant
        hits = (np.abs(determinant) > epsilon) & (
            u >= -epsilon) & (v >= -epsilon) & (
            u + v <= 1.0 + epsilon) & (
            distance >= -epsilon) & (distance <= max_distance + epsilon)
        indices = np.flatnonzero(hits)
        if not indices.size:
            return None
        return int(offsets[indices[np.argmin(distance[indices])]])


def raw_point_screen_position(mesh, xyz, matrix, width, height):
    """Project raw Papyrus XYZ, including authored plane-only/inline points.

    Use the same mesh centering and camera projection as visible geometry.
    Return None for invalid or clipped coordinates.
    """
    if mesh is None or xyz is None:
        return None
    raw = np.asarray(xyz, dtype=np.float64)
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


def vertex_screen_position(model, mesh, offset, matrix, width, height):
    """Project a compiled vertex, sharing the BSP raw-coordinate transform."""
    if model is None or offset not in model.vertices:
        return None
    return raw_point_screen_position(
        mesh, model.vertices[offset].xyz, matrix, width, height)


def bsp_winding_arrows(screen_points, marker_radius=10.0):
    """Generate directed 1→2, 2→3, 3→1 segments and arrowhead strokes.

    Returns (shaft_start, shaft_end, wing_left, wing_right) per visible edge.
    Endpoints are pulled away from vertex markers so arrowheads remain legible.
    Missing/clipped or coincident screen points never create wild coordinates.
    """
    if len(screen_points) != 3:
        return ()
    arrows = []
    for i in range(3):
        a, b = screen_points[i], screen_points[(i + 1) % 3]
        if a is None or b is None:
            continue
        delta = np.asarray(b, dtype=np.float64) - np.asarray(a, dtype=np.float64)
        length = float(np.linalg.norm(delta))
        if not np.isfinite(length) or length <= marker_radius * 2 + 9:
            continue
        unit = delta / length
        end = np.asarray(b, dtype=np.float64) - unit * (marker_radius + 2)
        start = np.asarray(a, dtype=np.float64) + unit * (marker_radius + 2)
        # Keep arrowhead fins in a predictable 2D plane.
        sideways = np.array([-unit[1], unit[0]])
        wing_distance = min(9.0, (length - marker_radius * 2) / 4)
        left = end - unit * wing_distance + sideways * wing_distance * 0.6
        right = end - unit * wing_distance - sideways * wing_distance * 0.6
        arrows.append(tuple(tuple(float(v) for v in p)
                            for p in (start, end, left, right)))
    return tuple(arrows)
