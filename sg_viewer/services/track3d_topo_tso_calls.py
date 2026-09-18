"""Read and update the per-section output TOPO/TSO calls in track .3D files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SectionTopoTsoCalls:
    section: str
    left: list[str]
    right: list[str]


_SECTION_RE = re.compile(r"(?m)^\s*(sec\d+_s\d+_(?:HI|MED|LO))\s*:")
_CALL_RE = re.compile(
    r"(?m)^(?P<indent>\s*)%\s*Output\s+(?P<side>left|right)\s+side\s+TSOs\s*\r?\n"
    r"(?P<list_indent>\s*)LIST\s*\{(?P<body>[^}]*)\}(?P<tail>\s*;?)"
)


def _items(body: str) -> list[str]:
    return [item.strip() for item in body.split(",") if item.strip()]


def parse_topo_tso_calls(path: str | Path) -> list[SectionTopoTsoCalls]:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    matches = list(_SECTION_RE.finditer(text))
    result: list[SectionTopoTsoCalls] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sides: dict[str, list[str]] = {}
        for call in _CALL_RE.finditer(text, match.end(), end):
            sides[call.group("side").lower()] = _items(call.group("body"))
        if sides:
            result.append(
                SectionTopoTsoCalls(
                    section=match.group(1),
                    left=sides.get("left", []),
                    right=sides.get("right", []),
                )
            )
    return result


def update_topo_tso_calls(path: str | Path, calls: list[SectionTopoTsoCalls]) -> int:
    """Replace matching output LIST bodies, preserving comments and formatting."""
    target = Path(path)
    text = target.read_text(encoding="utf-8", errors="replace")
    by_section = {entry.section: entry for entry in calls}
    sections = list(_SECTION_RE.finditer(text))
    edits: list[tuple[int, int, str]] = []
    for index, match in enumerate(sections):
        entry = by_section.get(match.group(1))
        if entry is None:
            continue
        end = sections[index + 1].start() if index + 1 < len(sections) else len(text)
        for call in _CALL_RE.finditer(text, match.end(), end):
            values = entry.left if call.group("side").lower() == "left" else entry.right
            body = " " + ", ".join(values) + " " if values else " "
            edits.append((call.start("body"), call.end("body"), body))
    for start, end, replacement in reversed(edits):
        text = text[:start] + replacement + text[end:]
    target.write_text(text, encoding="utf-8")
    return len(edits)
