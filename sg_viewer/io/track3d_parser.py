import re
import shutil
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path

from sg_viewer.io.track3d_catalog import parse_track3d_catalog


@dataclass
class Track3DObjectList:
    side: str
    section: int
    sub_index: int
    tso_ids: list[int]


@dataclass(frozen=True)
class Track3DSectionDlongList:
    section: int
    sub_index: int
    dlongs: tuple[int, ...]


LINE_RE = re.compile(r"ObjectList_([LR])(\d+)_(\d+): LIST\s*\{([^}]*)\};")


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


def save_object_lists_to_track3d(
    path: str | Path,
    object_lists: list[Track3DObjectList],
) -> Path:
    track3d_path = Path(path)
    original_text = track3d_path.read_text(encoding="utf-8", errors="ignore")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = track3d_path.with_suffix(f"{track3d_path.suffix}.bak_{timestamp}")
    shutil.copy2(track3d_path, backup_path)

    new_rows = [
        f"ObjectList_{entry.side}{entry.section}_{entry.sub_index}: LIST {{ "
        f"{', '.join(f'__TSO{tso_id}' for tso_id in entry.tso_ids)} "
        "};"
        for entry in object_lists
    ]

    lines = original_text.splitlines()
    first_match_index: int | None = None
    retained_lines: list[str] = []
    for line in lines:
        if LINE_RE.search(line):
            if first_match_index is None:
                first_match_index = len(retained_lines)
            continue
        retained_lines.append(line)

    insert_index = first_match_index if first_match_index is not None else len(retained_lines)
    updated_lines = retained_lines[:insert_index] + new_rows + retained_lines[insert_index:]
    track3d_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")

    return backup_path
