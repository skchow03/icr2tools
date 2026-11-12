"""Source-backed vertex table for the selected root POLY.

Display exactly the authored XYZ and T=<U,V> tokens when available. Changes
replace only one numeric source token, never patch the compiled 3DO or the
renderer directly. Unnamed inline vertices cannot be safely edited here.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import re

from n3_compile import _source_coordinate_scale
from polygon_split import polygon_boundary_refs
from source_symmetry import _VERTEX, mask_comments
from text_3d import parse_document
from three_do import INT32_HI, INT32_LO

_NUM = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_UV = re.compile(
    r"\bT\s*=\s*<\s*(?P<u>" + _NUM + r")\s*,\s*"
    r"(?P<v>" + _NUM + r")\s*>", re.I)


@dataclass(frozen=True)
class SourceVertex:
    label: str
    values: tuple[str, str, str, str | None, str | None]
    spans: tuple[tuple[int, int] | None, ...]


@dataclass(frozen=True)
class PolygonVertexRow:
    offset: int
    label: str
    values: tuple[str, str, str, str, str]
    editable: tuple[bool, bool, bool, bool, bool]


@dataclass(frozen=True)
class PolygonVertexEdit:
    label: str
    field: str
    before: str
    after: str
    start: int
    end: int

    @property
    def changed(self):
        return self.before != self.after


def source_vertex_declarations(source):
    """Gather numeric text/spans from complete, unique N3 vertex statements."""
    masked = mask_comments(source)
    declarations = {}
    duplicates = set()
    for match in _VERTEX.finditer(masked):
        label = match.group("label")
        if label in declarations:
            duplicates.add(label)
            continue
        xyz = tuple(source[s:e] for s, e in
                    (match.span(axis) for axis in "xyz"))
        uv = _UV.search(masked, match.end("z"), match.end())
        uv_spans = (uv.span("u"), uv.span("v")) if uv else (None, None)
        uv_values = tuple(source[s:e] if s is not None else None
                          for s, e in (span if span is not None else
                                       (None, None) for span in uv_spans))
        declarations[label] = SourceVertex(
            label, (*xyz, *uv_values),
            (*(match.span(axis) for axis in "xyz"), *uv_spans))
    for label in duplicates:
        del declarations[label]
    return declarations


def _row_lookup(model, source):
    declarations = source_vertex_declarations(source)
    by_offset = {}
    for label, offset in getattr(model, "n3_label_offsets", {}).items():
        if label in declarations:
            by_offset.setdefault(offset, declarations[label])
    return by_offset


def polygon_vertex_rows(model, poly_offset, source):
    """Ordered polygon boundary, including read-only anonymous vertices."""
    polygon = getattr(model, "polygons", {}).get(poly_offset)
    if polygon is None:
        return ()
    definitions = _row_lookup(model, source)
    rows = []
    for ref in polygon_boundary_refs(polygon):
        vertex = model.vertices.get(ref)
        if vertex is None:
            continue
        definition = definitions.get(ref)
        if definition is None:
            coords = tuple(str(value) for value in vertex.xyz)
            uv = tuple(str(v) for v in vertex.uv) if vertex.uv else ("", "")
            rows.append(PolygonVertexRow(
                ref, f"@{ref} (inline)", (*coords, *uv),
                (False, False, False, False, False)))
        else:
            x, y, z, u, v = definition.values
            textured = polygon.kind == 2 and vertex.uv is not None
            rows.append(PolygonVertexRow(
                ref, definition.label, (x, y, z, u or "", v or ""),
                (True, True, True, textured and u is not None,
                 textured and v is not None)))
    return tuple(rows)


def plan_polygon_vertex_edit(source, model, poly_offset, vertex_offset,
                             field, new_text):
    """Validate one text cell against the current compiled root vertex.

    Protect against editing stale geometry, changing implicit XYZ scale for
    the entire model, decimal UV rounding, and changing another polygon's
    vertex. Fail atomically before any QTextDocument mutation.
    """
    if field not in ("x", "y", "z", "u", "v"):
        raise ValueError("Choose X, Y, Z, U or V")
    row = next((r for r in polygon_vertex_rows(model, poly_offset, source)
                if r.offset == vertex_offset), None)
    if row is None:
        raise ValueError("That vertex no longer belongs to the selected POLY")
    index = ("x", "y", "z", "u", "v").index(field)
    if not row.editable[index]:
        raise ValueError("This vertex has no editable source declaration for that field")
    token = str(new_text).strip()
    if not re.fullmatch(_NUM, token):
        raise ValueError("Enter one finite numeric value, without units")
    try:
        new = Decimal(token)
    except InvalidOperation as exc:
        raise ValueError("Enter a valid numeric value") from exc
    if not new.is_finite():
        raise ValueError("The value must be finite")
    old = row.values[index]
    if old == token:
        return PolygonVertexEdit(row.label, field.upper(), old, token, 0, 0)
    definitions = source_vertex_declarations(source)
    definition = definitions.get(row.label)
    if definition is None or definition.spans[index] is None:
        raise ValueError("Vertex declaration changed; reselect the polygon")
    start, end = definition.spans[index]
    vertex = model.vertices[vertex_offset]
    if index < 3:
        scale = _source_coordinate_scale(
            source, parse_document(source, require_offsets=False).statements)
        for axis in range(3):
            old_numeric = Decimal(definition.values[axis])
            compiled = int((old_numeric * scale).to_integral_value(
                rounding=ROUND_HALF_EVEN))
            if compiled != vertex.xyz[axis]:
                raise ValueError("Source coordinates no longer match the compiled vertex")
        raw = int((new * scale).to_integral_value(rounding=ROUND_HALF_EVEN))
        if not INT32_LO <= raw <= INT32_HI:
            raise ValueError("XYZ exceeds the signed 32-bit Papyrus coordinate range")
        candidate = source[:start] + token + source[end:]
        candidate_scale = _source_coordinate_scale(
            candidate, parse_document(candidate, require_offsets=False).statements)
        if candidate_scale != scale:
            raise ValueError(
                "This change would alter the implicit coordinate scale of the "
                "whole model. Add an explicit ICR2_COORD_SCALE first.")
    else:
        if new != new.to_integral_value():
            raise ValueError("U and V must be whole-number texture coordinates")
        if not 0 <= new <= 65535:
            raise ValueError("U and V must be between 0 and 65535")
        if vertex.uv is None:
            raise ValueError("Vertex has no compiled texture coordinates")
        for axis in (3, 4):
            if definition.values[axis] is None or (
                    int(round(float(Decimal(definition.values[axis])))) !=
                    vertex.uv[axis - 3]):
                raise ValueError("Source UV no longer matches the compiled vertex")
    return PolygonVertexEdit(row.label, field.upper(), old, token, start, end)
