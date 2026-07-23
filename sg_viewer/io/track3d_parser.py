import re
import shutil
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path

from sg_viewer.io.track3d_catalog import (
    Track3DDetailListDefinition,
    Track3DObjectListDefinition,
    parse_track3d_catalog,
)


@dataclass
class Track3DObjectList:
    side: str
    section: int
    sub_index: int
    tso_ids: list[int]


@dataclass
class Track3DDetailList:
    section: int
    sub_index: int
    lod_suffix: str
    tso_ids: list[int]


@dataclass(frozen=True)
class Track3DDetailListDlongRange:
    section: int
    sub_index: int
    lod_suffix: str
    start_dlong: int | None
    end_dlong: int | None


@dataclass(frozen=True)
class Track3DBoundingBox:
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def length(self) -> float:
        return self.max_x - self.min_x

    @property
    def width(self) -> float:
        return self.max_y - self.min_y


@dataclass(frozen=True)
class Track3DSectionDlongList:
    section: int
    sub_index: int
    dlongs: tuple[int, ...]


_TRACK3D_VERTEX_RE = re.compile(
    r"\[<\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*>\]"
)


def calculate_track3d_xy_bounding_box(path: str | Path) -> Track3DBoundingBox:
    """Return the X/Y bounding box for vertex definitions in a text .3D file."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    xs: list[float] = []
    ys: list[float] = []
    for match in _TRACK3D_VERTEX_RE.finditer(text):
        xs.append(float(match.group(1)))
        ys.append(float(match.group(2)))
    if not xs or not ys:
        raise ValueError("No vertex coordinates were found in the selected .3D file.")
    return Track3DBoundingBox(
        min_x=min(xs),
        min_y=min(ys),
        max_x=max(xs),
        max_y=max(ys),
    )


def parse_track3d(path: str | Path) -> list[Track3DObjectList]:
    catalog = parse_track3d_catalog(path)
    results: list[Track3DObjectList] = []

    for object_list in catalog.object_lists.values():
        tso_ids: list[int] = []
        for item in object_list.items:
            if not item.startswith("__TSO"):
                continue
            try:
                tso_ids.append(int(item.removeprefix("__TSO")))
            except ValueError:
                continue

        results.append(
            Track3DObjectList(
                side=object_list.side,
                section=object_list.section,
                sub_index=object_list.subsection,
                tso_ids=tso_ids,
            )
        )

    return results


def track3d_has_object_lists(path: str | Path) -> bool:
    return bool(parse_track3d_catalog(path).object_lists)


def parse_track3d_detail_lists(path: str | Path) -> list[Track3DDetailList]:
    catalog = parse_track3d_catalog(path)
    results: list[Track3DDetailList] = []

    for detail_list in catalog.detail_lists.values():
        tso_ids: list[int] = []
        for item in detail_list.items:
            if not item.startswith("__TSO"):
                continue
            try:
                tso_ids.append(int(item.removeprefix("__TSO")))
            except ValueError:
                continue

        results.append(
            Track3DDetailList(
                section=detail_list.section,
                sub_index=detail_list.subsection,
                lod_suffix=detail_list.lod_suffix,
                tso_ids=tso_ids,
            )
        )

    return results


def track3d_has_detail_lists(path: str | Path) -> bool:
    return bool(parse_track3d_catalog(path).detail_lists)


def parse_track3d_detail_list_dlong_ranges(
    path: str | Path,
) -> list[Track3DDetailListDlongRange]:
    catalog = parse_track3d_catalog(path)
    ranges: dict[str, list[tuple[int | None, int | None]]] = {
        label: [] for label in catalog.detail_lists
    }
    for face in catalog.faces:
        for label in face.detail_lists:
            if label in ranges:
                ranges[label].append((face.dlong_start, face.dlong_end))

    results: list[Track3DDetailListDlongRange] = []
    for label, detail in catalog.detail_lists.items():
        face_ranges = ranges.get(label, [])
        starts = [start for start, _end in face_ranges if start is not None]
        ends = [end for _start, end in face_ranges if end is not None]
        results.append(
            Track3DDetailListDlongRange(
                section=detail.section,
                sub_index=detail.subsection,
                lod_suffix=detail.lod_suffix,
                start_dlong=min(starts) if starts else None,
                end_dlong=max(ends) if ends else None,
            )
        )
    return results


def parse_track3d_section_dlongs(path: str | Path) -> list[Track3DSectionDlongList]:
    catalog = parse_track3d_catalog(path)
    results: list[Track3DSectionDlongList] = []

    for section_list in catalog.section_lists.values():
        if not section_list.dlongs:
            continue

        results.append(
            Track3DSectionDlongList(
                section=section_list.section,
                sub_index=section_list.layout,
                dlongs=tuple(section_list.dlongs),
            )
        )

    return results


def _object_list_label(entry: Track3DObjectList) -> str:
    return f"ObjectList_{entry.side}{entry.section}_{entry.sub_index}"


def _format_object_list_row(entry: Track3DObjectList) -> str:
    return (
        f"{_object_list_label(entry)}: LIST {{ "
        f"{', '.join(f'__TSO{tso_id}' for tso_id in entry.tso_ids)} "
        "};"
    )


def _choose_object_list_insert_offset(
    original_text: str,
    catalog_object_lists: dict[str, Track3DObjectListDefinition],
    entry: Track3DObjectList,
) -> tuple[int, str]:
    """Return insertion offset and text placement mode for a missing ObjectList.

    The mode is ``before``, ``after``, or ``append`` and controls newline padding.
    Existing definitions for the same side/section are preferred; otherwise the
    new row is appended after the existing ObjectList block.
    """
    same_section_side = [
        object_list
        for object_list in catalog_object_lists.values()
        if object_list.side == entry.side and object_list.section == entry.section
    ]
    if same_section_side:
        closest = min(
            same_section_side,
            key=lambda object_list: (
                abs(object_list.subsection - entry.sub_index),
                object_list.subsection,
            ),
        )
        if entry.sub_index < closest.subsection:
            return closest.span.start_offset or 0, "before"
        return closest.span.end_offset or len(original_text), "after"

    if catalog_object_lists:
        last_object_list = max(
            catalog_object_lists.values(),
            key=lambda object_list: object_list.span.end_offset or -1,
        )
        return last_object_list.span.end_offset or len(original_text), "after"

    return len(original_text), "append"


def _insertion_text(row: str, mode: str, original_text: str, offset: int) -> str:
    if mode == "before":
        return row + "\n"
    if mode == "after":
        return "\n" + row
    if not original_text:
        return row + "\n"
    prefix = "" if original_text.endswith("\n") else "\n"
    return prefix + row + "\n"


def save_object_lists_to_track3d(
    path: str | Path,
    object_lists: list[Track3DObjectList],
    *,
    create_backup: bool = True,
) -> Path | None:
    track3d_path = Path(path)
    original_text = track3d_path.read_text(encoding="utf-8", errors="ignore")
    catalog = parse_track3d_catalog(track3d_path)

    backup_path = None
    if create_backup:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = track3d_path.with_suffix(f"{track3d_path.suffix}.bak_{timestamp}")
        shutil.copy2(track3d_path, backup_path)

    replacements: list[tuple[int, int, str]] = []
    insertions: dict[tuple[int, str], list[str]] = {}

    for entry in object_lists:
        label = _object_list_label(entry)
        row = _format_object_list_row(entry)
        existing = catalog.object_lists.get(label)
        if existing is not None:
            start_offset = existing.span.start_offset
            end_offset = existing.span.end_offset
            if start_offset is not None and end_offset is not None:
                replacements.append((start_offset, end_offset, row))
            continue

        offset, mode = _choose_object_list_insert_offset(
            original_text,
            catalog.object_lists,
            entry,
        )
        insertions.setdefault((offset, mode), []).append(row)

    edits: list[tuple[int, int, str]] = replacements[:]
    for (offset, mode), rows in insertions.items():
        text = _insertion_text("\n".join(rows), mode, original_text, offset)
        edits.append((offset, offset, text))

    updated_text = original_text
    for start_offset, end_offset, replacement_text in sorted(
        edits,
        key=lambda edit: (edit[0], edit[1]),
        reverse=True,
    ):
        updated_text = (
            updated_text[:start_offset] + replacement_text + updated_text[end_offset:]
        )

    track3d_path.write_text(updated_text, encoding="utf-8")

    return backup_path


def _detail_list_label(entry: Track3DDetailList) -> str:
    return f"DetailList_{entry.section}-{entry.sub_index}{entry.lod_suffix}"


def _format_detail_list_row(
    existing: Track3DDetailListDefinition, entry: Track3DDetailList
) -> str:
    non_tso_items = [item for item in existing.items if not item.startswith("__TSO")]
    items = non_tso_items + [f"__TSO{tso_id}" for tso_id in entry.tso_ids]
    return f"{_detail_list_label(entry)}: LIST {{ {', '.join(items)} }};"


def save_detail_lists_to_track3d(
    path: str | Path,
    detail_lists: list[Track3DDetailList],
    *,
    create_backup: bool = True,
) -> Path | None:
    track3d_path = Path(path)
    original_text = track3d_path.read_text(encoding="utf-8", errors="ignore")
    catalog = parse_track3d_catalog(track3d_path)

    backup_path = None
    if create_backup:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = track3d_path.with_suffix(f"{track3d_path.suffix}.bak_{timestamp}")
        shutil.copy2(track3d_path, backup_path)

    edits: list[tuple[int, int, str]] = []
    for entry in detail_lists:
        existing = catalog.detail_lists.get(_detail_list_label(entry))
        if existing is None:
            continue
        start_offset = existing.span.start_offset
        end_offset = existing.span.end_offset
        if start_offset is None or end_offset is None:
            continue
        edits.append(
            (start_offset, end_offset, _format_detail_list_row(existing, entry))
        )

    updated_text = original_text
    for start_offset, end_offset, replacement_text in sorted(
        edits, key=lambda edit: (edit[0], edit[1]), reverse=True
    ):
        updated_text = (
            updated_text[:start_offset] + replacement_text + updated_text[end_offset:]
        )

    track3d_path.write_text(updated_text, encoding="utf-8")
    return backup_path
