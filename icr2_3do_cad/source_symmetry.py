"""Conservative, pure-text mirror editing of named Papyrus N3 vertices.

Only the three numeric tokens inside a declaration's [<X,Y,Z>] are ever
changed. UV/T values, comments, names, polygons and other statements stay
byte-for-byte identical. Pairing uses the previously *validated* source,
not the newly moved coordinate. No model binary or GL dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

_NAME = r"[A-Za-z_][A-Za-z_0-9-]*"
_NUM = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_VERTEX = re.compile(
    r"(?m)^[ \t]*(?P<label>" + _NAME + r")[ \t]*:[ \t]*"
    r"\[[ \t\r\n]*<[ \t\r\n]*"
    r"(?P<x>" + _NUM + r")[ \t\r\n]*,[ \t\r\n]*"
    r"(?P<y>" + _NUM + r")[ \t\r\n]*,[ \t\r\n]*"
    r"(?P<z>" + _NUM + r")[ \t\r\n]*>"
    r"[ \t\r\n]*(?:,[^\]]*)?\][ \t]*;",
)
_PLANES = {"X": 0, "Y": 1, "Z": 2}


@dataclass(frozen=True)
class NamedVertex:
    label: str
    xyz: tuple[Decimal, Decimal, Decimal]
    spans: tuple[tuple[int, int], tuple[int, int], tuple[int, int]]
    line: int


@dataclass(frozen=True)
class MirrorEdit:
    source: NamedVertex
    moved: NamedVertex
    candidates: tuple[NamedVertex, ...]


@dataclass(frozen=True)
class MirrorIssue:
    label: str
    reason: str


def mask_comments(source):
    """Mask '%' N3 comments without changing source offsets or line numbers."""
    lines = source.splitlines(keepends=True)
    result = []
    for line in lines:
        in_string = False
        start = None
        for i, char in enumerate(line):
            if char == '"':
                in_string = not in_string
            if char == '%' and not in_string:
                start = i
                break
        result.append(line if start is None else
                      line[:start] + ''.join(
                          c if c in '\r\n' else ' ' for c in line[start:]))
    return ''.join(result)


def named_vertices(source):
    """Index complete named vertex declarations; reject duplicate labels.

    Operates on raw authored coordinates, not the model's normalized mesh.
    Incomplete edits are omitted, and the caller must not compile/apply an
    automatic mirror before the user's typing forms a valid declaration.
    """
    masked = mask_comments(source)
    vertices = {}
    for match in _VERTEX.finditer(masked):
        label = match.group("label")
        if label in vertices:
            raise ValueError(f"Duplicate vertex declaration: {label}")
        try:
            xyz = tuple(Decimal(match.group(axis)) for axis in "xyz")
        except InvalidOperation:
            continue
        if not all(value.is_finite() for value in xyz):
            continue
        vertices[label] = NamedVertex(
            label, xyz, tuple(match.span(axis) for axis in "xyz"),
            source.count('\n', 0, match.start()) + 1)
    return vertices


def mirror_xyz(xyz, axis, plane_at=Decimal(0)):
    if axis not in _PLANES:
        raise ValueError("Choose X, Y or Z as the mirror-axis normal")
    c = Decimal(str(plane_at))
    if not c.is_finite():
        raise ValueError("Mirror-plane position must be finite")
    result = list(xyz)
    n = _PLANES[axis]
    result[n] = 2 * c - result[n]
    return tuple(result)


def _within(a, b, tolerance):
    return all(abs(x-y) <= tolerance for x, y in zip(a, b))


def plan_mirrored_vertices(original, current, *, axis, plane_at=0,
                           tolerance=0):
    """Plan mirror updates from stable pre-edit geometry.

    Returns (proposals, issues), without editing the source. If a vertex
    lies ON the plane it is handled separately (no opposite vertex); if
    both vertices were already edited, do not overwrite either one.
    """
    if axis not in _PLANES:
        raise ValueError("Mirror plane must be X=constant, Y=constant or Z=constant")
    center = Decimal(str(plane_at))
    tol = Decimal(str(tolerance))
    if not center.is_finite() or not tol.is_finite() or tol < 0:
        raise ValueError("Mirror plane offset/tolerance must be finite; tolerance >= 0")
    old = named_vertices(original)
    new = named_vertices(current)
    modified = {label for label, source in old.items()
                if label in new and source.xyz != new[label].xyz}
    proposals = []
    issues = []
    idx = _PLANES[axis]
    for label in sorted(modified):
        source, moved = old[label], new[label]
        if abs(source.xyz[idx] - center) <= tol:
            if abs(moved.xyz[idx] - center) > tol:
                issues.append(MirrorIssue(
                    label, f"{label} was on {axis}={center} but moved off the mirror plane; "
                    "no opposite vertex was changed."))
            continue
        mirror_point = mirror_xyz(source.xyz, axis, center)
        candidates = tuple(
            entry for other_label, entry in old.items()
            if other_label != label and other_label in new
            and _within(entry.xyz, mirror_point, tol))
        if not candidates:
            issues.append(MirrorIssue(
                label, f"{label}: no mirrored vertex at {mirror_point} "
                f"(tolerance {tol})."))
            continue
        # When a user manually edited both halves, preserve both changes
        # rather than doing two incompatible automatic swaps.
        eligible = tuple(c for c in candidates if c.label not in modified)
        if not eligible:
            if len(candidates) == 1 and _within(
                    new[candidates[0].label].xyz,
                    mirror_xyz(moved.xyz, axis, center), tol):
                continue
            issues.append(MirrorIssue(
                label, f"{label}: counterpart was also edited manually; "
                "no automatic overwrite was made."))
            continue
        proposals.append(MirrorEdit(source, moved, eligible))
    return proposals, issues


def coordinate_replacements(current, selected, *, axis, plane_at=0):
    """For resolved (MirrorEdit, target-label) choices, produce raw XYZ edits.

    Every position refers to the unchanged current source. The caller
    applies replacements in descending offset order to keep spans stable.
    """
    vertices = named_vertices(current)
    proposed = {}
    for edit, target_label in selected:
        if target_label not in {c.label for c in edit.candidates}:
            raise ValueError("Mirror target must be one of the validated candidates")
        replacement = mirror_xyz(edit.moved.xyz, axis, plane_at)
        if target_label in proposed and proposed[target_label] != replacement:
            raise ValueError(f"Conflicting mirror edits for {target_label}")
        proposed[target_label] = replacement
    edits = []
    for label, xyz in proposed.items():
        vertex = vertices[label]
        for old_value, token_span, new_value in zip(vertex.xyz, vertex.spans, xyz):
            if old_value == new_value:
                continue
            # Use decimal text as plain N3 coordinates; no UV fields touched.
            rendered = format(new_value, "f").rstrip("0").rstrip(".") if (
                new_value == new_value.to_integral_value()) is False else format(new_value, "f")
            if "." in rendered:
                rendered = rendered.rstrip("0").rstrip(".")
            if rendered in ("", "-0"):
                rendered = "0"
            edits.append((token_span[0], token_span[1], rendered))
    return sorted(edits, reverse=True)


def apply_replacements(source, edits):
    result = source
    previous_start = len(result) + 1
    for start, end, value in edits:
        if not (0 <= start < end <= previous_start):
            raise ValueError("Overlapping or invalid mirror replacement spans")
        result = result[:start] + value + result[end:]
        previous_start = start
    return result
