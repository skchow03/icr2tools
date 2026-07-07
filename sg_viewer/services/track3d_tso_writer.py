from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

from sg_viewer.io.track3d_catalog import Track3DCatalog, parse_track3d_catalog
from sg_viewer.services.trackside_objects import TracksideObject, normalize_trackside_filename


def track3d_newline_style(text: str) -> str:
    first_crlf = text.find("\r\n")
    first_lf = text.find("\n")
    if first_crlf >= 0 and (first_lf < 0 or first_crlf <= first_lf):
        return "\r\n"
    return "\n"


def format_tso_dynamic_line(label: str, obj: TracksideObject) -> str:
    return (
        f'{label}: DYNAMIC {obj.x}, {obj.y}, {obj.z}, {obj.yaw}, '
        f'{obj.pitch}, {obj.tilt}, 1, EXTERN "{normalize_trackside_filename(obj.filename)}";'
    )


def _trackside_object_catalog_key(obj: TracksideObject) -> tuple[str, int, int, int, int, int, int]:
    return (
        normalize_trackside_filename(obj.filename).lower(),
        int(obj.x),
        int(obj.y),
        int(obj.z),
        int(obj.yaw),
        int(obj.pitch),
        int(obj.tilt),
    )


def replace_tso_dynamic_section_in_3d_text(
    text: str,
    project_objects: list[TracksideObject] | tuple[TracksideObject, ...],
    catalog: Track3DCatalog | None = None,
) -> tuple[str, int, int]:
    if catalog is None:
        with NamedTemporaryFile("w", suffix=".3d", encoding="utf-8", delete=False) as temp_file:
            temp_file.write(text)
            temp_path = Path(temp_file.name)
        try:
            catalog = parse_track3d_catalog(temp_path)
        finally:
            temp_path.unlink(missing_ok=True)
    if not catalog.tsos:
        return text, 0, 0

    project_objects = list(project_objects)
    existing_by_label = sorted(catalog.tsos.items(), key=lambda item: int(item[0][5:]))
    available_labels = [label for label, _definition in existing_by_label]
    assigned_labels: dict[int, str] = {}
    used_labels: set[str] = set()

    unmatched_by_key: dict[tuple[str, int, int, int, int, int, int], list[str]] = {}
    for label, definition in existing_by_label:
        existing_obj = TracksideObject(
            filename=normalize_trackside_filename(definition.extern),
            x=int(definition.x),
            y=int(definition.y),
            z=int(definition.z),
            yaw=int(definition.rot),
            pitch=int(definition.params[4]) if len(definition.params) > 4 else 0,
            tilt=int(definition.params[5]) if len(definition.params) > 5 else 0,
        )
        unmatched_by_key.setdefault(_trackside_object_catalog_key(existing_obj), []).append(label)

    for index, obj in enumerate(project_objects):
        labels = unmatched_by_key.get(_trackside_object_catalog_key(obj))
        if labels:
            label = labels.pop(0)
            assigned_labels[index] = label
            used_labels.add(label)

    unused_existing_labels = [label for label in available_labels if label not in used_labels]
    for index, _obj in enumerate(project_objects):
        if index in assigned_labels:
            continue
        if unused_existing_labels:
            label = unused_existing_labels.pop(0)
        else:
            next_id = 0
            existing_ids = {int(label[5:]) for label in available_labels}
            while next_id in existing_ids:
                next_id += 1
            label = f"__TSO{next_id}"
            available_labels.append(label)
        assigned_labels[index] = label
        used_labels.add(label)

    replacements: list[tuple[int, int, str]] = []
    newline = track3d_newline_style(text)
    for index, label in assigned_labels.items():
        if label not in catalog.tsos:
            continue
        span = catalog.tsos[label].span
        if span.start_offset is None or span.end_offset is None:
            continue
        replacements.append((span.start_offset, span.end_offset, format_tso_dynamic_line(label, project_objects[index])))

    deleted_labels = [label for label in catalog.tsos if label not in used_labels]
    for label in deleted_labels:
        span = catalog.tsos[label].span
        if span.start_offset is None or span.end_offset is None:
            continue
        start = span.start_offset
        end = span.end_offset
        if end < len(text) and text[end : end + 2] == "\r\n":
            end += 2
        elif end < len(text) and text[end : end + 1] == "\n":
            end += 1
        replacements.append((start, end, ""))

    new_entries = [
        format_tso_dynamic_line(assigned_labels[index], obj)
        for index, obj in enumerate(project_objects)
        if assigned_labels[index] not in catalog.tsos
    ]
    if new_entries:
        last_span = max(
            (definition.span for definition in catalog.tsos.values() if definition.span.end_offset is not None),
            key=lambda span: span.end_offset or 0,
        )
        insert_at = last_span.end_offset or len(text)
        line_break_follows = text[insert_at : insert_at + len(newline)] == newline
        insertion = newline + newline.join(new_entries)
        if not line_break_follows:
            insertion += newline
        replacements.append((insert_at, insert_at, insertion))

    updated = text
    for start, end, replacement in sorted(replacements, key=lambda item: item[0], reverse=True):
        updated = updated[:start] + replacement + updated[end:]
    return updated, len(catalog.tsos), len(deleted_labels)
