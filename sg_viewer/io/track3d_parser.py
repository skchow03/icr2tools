import re
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
