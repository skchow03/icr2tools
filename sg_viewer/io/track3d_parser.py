import re
import shutil
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Track3DObjectList:
    side: str
    section: int
    sub_index: int
    tso_ids: list[int]


LINE_RE = re.compile(r"ObjectList_([LR])(\d+)_(\d+): LIST\s*\{([^}]*)\};")


def parse_track3d(path: str | Path) -> list[Track3DObjectList]:
    results: list[Track3DObjectList] = []

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            match = LINE_RE.search(line)
            if not match:
                continue

            side = match.group(1)
            section = int(match.group(2))
            sub_index = int(match.group(3))
            raw = match.group(4).strip()

            tso_ids: list[int] = []
            if raw:
                for item in raw.split(","):
                    item = item.strip()
                    if item.startswith("__TSO"):
                        tso_ids.append(int(item.replace("__TSO", "")))

            results.append(
                Track3DObjectList(
                    side=side,
                    section=section,
                    sub_index=sub_index,
                    tso_ids=tso_ids,
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
