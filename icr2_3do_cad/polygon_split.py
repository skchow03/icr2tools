"""Source-preserving polygon splitting for the GPU N3 editor.

The existing Model topology splitter validates geometry and neighbor repairs.
This adapter translates its result into a small, undoable N3 source edit:
existing declarations and their authored names remain intact. Nothing is
written to disk; the normal GPU source compiler validates the new document.
"""
from __future__ import annotations

from copy import copy
from dataclasses import dataclass, replace
from decimal import Decimal, localcontext
import re

from text_3d import parse_document
from three_do import FormatError
from source_inspection import target_offset


_POLY = re.compile(r"\bPOLY(?:\s+\[T\])?\s+[^{}]*?\{[^{}]*\}", re.I | re.S)
_BINARY_LABEL = re.compile(r"^_(\d+)$")
_HEADER = re.compile(
    r"(?im)^[ \t]*3D[ \t]+VERSION[ \t]+3\.0[ \t]*;?"
    r"[ \t]*(?:%[^\r\n]*)?(?:\r?\n|$)"
)


@dataclass(frozen=True)
class SourceSplitResult:
    source: str
    first_polygon_label: str
    second_polygon_label: str
    new_vertices: int
    updated_neighbors: int
    warnings: tuple[str, ...]


def polygon_boundary_refs(polygon):
    """N3 compiler closes each POLY with a repeated first pointer.

    The CPU topology algorithms use open cyclic boundary lists. Exclude only
    the deliberate trailing closure; never collapse internal duplicate refs.
    """
    refs = tuple(polygon.refs)
    if len(refs) > 3 and refs[0] == refs[-1]:
        return refs[:-1]
    return refs


def _open_boundary_model(model):
    """Read-only temporary input for CPU splitter; binary/source unchanged.

    The normal GPU N3 compiler emits a repeated closing ref for every POLY.
    Create a shallow Model snapshot with normalized polygon boundary lists
    solely for geometric split computations. The splitter still produces and
    reparses a fully validated 3DO, and the GUI persists only its N3 result.
    """
    if not any(polygon_boundary_refs(p) != tuple(p.refs)
               for p in model.polygons.values()):
        return model
    prepared = copy(model)
    prepared.polygons = {
        off: (replace(poly, refs=polygon_boundary_refs(poly))
              if polygon_boundary_refs(poly) != tuple(poly.refs) else poly)
        for off, poly in model.polygons.items()
    }
    return prepared


def _model_label_offset(model, label):
    mapping = getattr(model, "n3_label_offsets", {})
    if label in mapping:
        return mapping[label]
    match = _BINARY_LABEL.fullmatch(label)
    if match:
        return int(match.group(1))
    if label == "root":
        return model.root_offset
    return None


def _polygon_declaration(model, statements, offset):
    for statement in statements:
        if _POLY.search(statement.command) is None:
            continue
        if target_offset(model, "polygon", statement.label) == offset:
            return statement
    raise FormatError(
        f"POLY @{offset} has no individually editable N3 declaration. "
        "Name this polygon (or its direct MATERIAL wrapper) in .3D Source "
        "before splitting; anonymous polygons nested inside LIST/BSP "
        "expressions cannot be changed safely."
    )


def _distinct_name(base, used):
    candidate = re.sub(r"[^A-Za-z_0-9]", "_", base)
    if not candidate or candidate[0].isdigit():
        candidate = "_" + candidate
    root = candidate
    suffix = 2
    while candidate.lower() in used:
        candidate = f"{root}_{suffix}"
        suffix += 1
    used.add(candidate.lower())
    return candidate


def _coordinate(value, scale):
    if scale == 1:
        return str(int(value))
    # Source models with a % ICR2_COORD_SCALE hint interpret new XYZ in
    # authoring units, not raw compiled coordinates. Enough decimal places
    # are kept to reproduce the exact integer after compiler rounding.
    with localcontext() as ctx:
        ctx.prec = 60
        return format(Decimal(int(value)) / Decimal(str(scale)), "f")


def _replace_polygon_refs(command, labels):
    matched = _POLY.search(command)
    if matched is None:
        raise FormatError("Expected a direct or MATERIAL-wrapped POLY declaration")
    expression = matched.group()
    opening = expression.index("{")
    replacement = expression[:opening + 1] + ", ".join(labels) + "}"
    return command[:matched.start()] + replacement + command[matched.end():]


def _replace_with_list(command, label_a, label_b):
    matched = _POLY.search(command)
    if matched is None:
        raise FormatError("Expected a direct or MATERIAL-wrapped POLY declaration")
    replacement = f"LIST {{{label_a}, {label_b}}}"
    # If a MATERIAL has an inline POLY child, preserve the MIP/GROUP wrapper.
    return command[:matched.start()] + replacement + command[matched.end():]


def _rewrite_declarations(source, changes):
    """Replace only the affected command spans, not the rest of the source."""
    replacements = []
    for label, new_command in changes.items():
        expression = re.compile(
            rf"(?m)^([ \t]*{re.escape(label)}[ \t]*:[ \t]*)(.*?)(;)",
            re.S,
        )
        match = expression.search(source)
        if match is None:
            raise FormatError(f"Missing N3 declaration {label!r}")
        replacements.append((match.start(2), match.end(2), new_command))
    for start, end, new_command in sorted(replacements, reverse=True):
        source = source[:start] + new_command + source[end:]
    return source


def split_n3_polygon(model, source, polygon_offset, *, mode="edges",
                     index_a=0, index_b=2, fraction_a=0.5,
                     fraction_b=0.5) -> SourceSplitResult:
    """Split one named root-model POLY and preserve the surrounding N3.

    mode='edges' inserts two interpolated points (and repairs exact-reference
    neighbors); mode='vertices' uses an interior diagonal without new points.
    Source editability is checked *before* accepting any geometry change.
    """
    if polygon_offset not in model.polygons:
        raise FormatError("Select a root-model polygon first")
    document = parse_document(source, require_offsets=False)
    statements = document.statements
    selected = _polygon_declaration(model, statements, polygon_offset)
    working = _open_boundary_model(model)
    if mode == "edges":
        updated, result = working.split_polygon(
            polygon_offset, index_a, index_b, fraction_a, fraction_b)
    elif mode == "vertices":
        updated, result = working.split_polygon_at_vertices(
            polygon_offset, index_a, index_b)
    else:
        raise ValueError("Unknown polygon split mode")

    neighbors = [(old, _polygon_declaration(model, statements, old))
                 for old, _ in result.updated_neighbors]
    used = {entry.label.lower() for entry in statements}
    first = _distinct_name("split_" + selected.label + "_a", used)
    second = _distinct_name("split_" + selected.label + "_b", used)
    new_labels = {}
    for number, offset in enumerate(result.new_vertices, start=1):
        new_labels[offset] = _distinct_name(
            f"split_{selected.label}_v{number}", used)

    # Every pre-existing vertex referenced by the split must have a stable
    # N3 declaration; do not silently change anonymous inline geometry.
    vertex_labels = {}
    for statement in statements:
        if statement.command.lstrip().startswith("[<"):
            offset = _model_label_offset(model, statement.label)
            if offset in model.vertices:
                vertex_labels[offset] = statement.label
    vertex_labels.update(new_labels)

    def references(polygon):
        try:
            return [vertex_labels[ref] for ref in polygon.refs]
        except KeyError as exc:
            raise FormatError(
                f"Vertex @{exc.args[0]} has no named N3 source declaration. "
                "Use named vertices before splitting this polygon."
            ) from exc

    changes = {selected.label: _replace_with_list(
        selected.command, first, second)}
    additions = []
    scale = getattr(model, "n3_coordinate_scale", 1)
    for offset, label in new_labels.items():
        vertex = updated.vertices[offset]
        xyz = ", ".join(_coordinate(v, scale) for v in vertex.xyz)
        uv = (f", T=<{vertex.uv[0]}, {vertex.uv[1]}>"
              if vertex.textured else "")
        additions.append(f"{label}: [<{xyz}>{uv}];")

    for offset, label in zip(result.new_polygons, (first, second)):
        polygon = updated.polygons[offset]
        kind = "POLY [T]" if polygon.kind == 2 else "POLY"
        additions.append(
            f"{label}: {kind} <{polygon.color}> "
            "{" + ", ".join(references(polygon)) + "};")

    for old_offset, statement in neighbors:
        replacement_offset = dict(result.updated_neighbors)[old_offset]
        changes[statement.label] = _replace_polygon_refs(
            statement.command, references(updated.polygons[replacement_offset]))

    # Validation-before-replacement. Missing labels/unsupported inline syntax
    # must leave the editable document entirely unchanged.
    changed = _rewrite_declarations(source, changes)
    header = _HEADER.search(changed)
    if header is None:
        raise FormatError("Expected a 3D VERSION 3.0 header")
    insertion = "\n".join(additions) + "\n"
    changed = changed[:header.end()] + insertion + changed[header.end():]
    parse_document(changed, require_offsets=False)
    return SourceSplitResult(
        source=changed,
        first_polygon_label=first,
        second_polygon_label=second,
        new_vertices=len(result.new_vertices),
        updated_neighbors=len(result.updated_neighbors),
        warnings=tuple(result.warnings),
    )
