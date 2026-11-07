"""Plan precise edits of a *single named N3 vertex* from raw Papyrus XYZ.

Preserve authored coordinate scale, literal U/V/T values, comments, names
and unrelated declarations. Only the three XYZ numeric spans may change.
Source is never modified on a validation, range or pairing error.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN, localcontext

from n3_compile import _source_coordinate_scale
from source_symmetry import named_vertices
from text_3d import parse_document
from three_do import INT32_HI, INT32_LO


@dataclass(frozen=True)
class VertexMovePlan:
    label: str
    before: tuple[int, int, int]
    after: tuple[int, int, int]
    edits: tuple[tuple[int, int, str], ...]

    @property
    def changed(self):
        return bool(self.edits)


def _compiled_value(authored, scale):
    return int((authored * scale).to_integral_value(rounding=ROUND_HALF_EVEN))


def plan_vertex_move(source, label, compiled_xyz, requested_xyz):
    """Compute descending text spans for an exact one-vertex move.

    The N3 compiler applies either explicit ICR2_COORD_SCALE or its
    implicit fractional-coordinate scale. Respect that effective scale,
    but never introduce fractional source when the original scale is 1.
    """
    original = tuple(int(value) for value in compiled_xyz)
    target = tuple(int(value) for value in requested_xyz)
    if len(original) != 3 or len(target) != 3:
        raise ValueError("Vertex XYZ must contain exactly three coordinates")
    if any(not (INT32_LO <= x <= INT32_HI) for x in target):
        raise ValueError("Target vertex coordinate exceeds signed 32-bit Papyrus range")
    vertices = named_vertices(source)
    if label not in vertices:
        raise ValueError(f"No complete named N3 vertex declaration for {label!r}")
    vertex = vertices[label]
    document = parse_document(source, require_offsets=False)
    scale = _source_coordinate_scale(source, document.statements)
    if any(_compiled_value(vertex.xyz[i], scale) != original[i]
           for i in range(3)):
        raise ValueError(
            f"{label}: source XYZ no longer matches the compiled vertex. "
            "Apply pending edits before moving the vertex.")
    edits = []
    with localcontext() as ctx:
        ctx.prec = 55
        for axis, (old, new) in enumerate(zip(original, target)):
            if new == old:
                continue
            authored = Decimal(new) / scale
            # A repeating authored decimal needs a finite, compiler-stable
            # representation; 12 places suffice for scale <= 1,000,000.
            if authored != authored.to_integral_value():
                authored = authored.quantize(
                    Decimal("0.000000000001"), rounding=ROUND_HALF_EVEN)
            token = format(authored, "f")
            if "." in token:
                token = token.rstrip("0").rstrip(".")
            if token in ("-0", ""):
                token = "0"
            if _compiled_value(Decimal(token), scale) != new:
                raise ValueError(
                    f"Unable to represent raw {new} at source scale {scale}")
            start, end = vertex.spans[axis]
            edits.append((start, end, token))
    return VertexMovePlan(label, original, target, tuple(sorted(edits, reverse=True)))
