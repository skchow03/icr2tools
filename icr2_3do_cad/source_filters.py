"""Read-only categorization of Papyrus N3 source for quick navigation.

Filters are deliberately separate from the QTextDocument. All declarations,
comments, whitespace and source offsets remain untouched by filtering.
"""
from __future__ import annotations

from dataclasses import dataclass
import re


CATEGORIES = (
    "Comments (%)",
    "POLY",
    "Vertices",
    "LIST",
    "BSP",
    "FACE",
    "SWITCH",
    "MATERIAL",
    "DYNAMIC",
    "LINE",
    "RECOLOR",
    "Sprites",
    "Other",
)

_DECLARATION = re.compile(r"^[ \t]*[A-Za-z_][A-Za-z_0-9-]*[ \t]*:[ \t]*")
_START = re.compile(r"^[ \t]*[A-Za-z_][A-Za-z_0-9-]*[ \t]*:", re.I)
_WORD = re.compile(r"^([A-Za-z_][A-Za-z_0-9-]*)\b")


@dataclass(frozen=True)
class SourceEntry:
    first_line: int  # original 0-based QTextBlock number
    last_line: int
    category: str
    preview: str


def _code(line: str) -> str:
    """Remove N3 % comments without mistaking quoted % or ; for syntax."""
    quoted = False
    for i, char in enumerate(line):
        if char == '"':
            quoted = not quoted
        elif char == "%" and not quoted:
            return line[:i]
    return line


def _finished(line: str) -> bool:
    """Find an actual statement terminator, ignoring strings and comments."""
    quoted = False
    for char in _code(line):
        if char == '"':
            quoted = not quoted
        elif char == ";" and not quoted:
            return True
    return False


def classify_statement(line: str) -> str:
    """Classify the declaration's command rather than identifiers in comments."""
    text = _code(line).strip()
    if not text:
        return "Comments (%)" if line.lstrip().startswith("%") else "Other"
    text = _DECLARATION.sub("", text, count=1).lstrip()
    if re.match(r"^\[\s*<", text):
        return "Vertices"
    match = _WORD.match(text)
    command = match.group(1).upper() if match else ""
    if command in ("POLY",):
        return "POLY"
    if command == "LIST":
        return "LIST"
    if command.startswith("BSP"):
        return "BSP"
    if command in ("FACE", "FACE2"):
        return "FACE"
    if command == "SWITCH":
        return "SWITCH"
    if command == "MATERIAL":
        return "MATERIAL"
    if command == "DYNAMIC":
        return "DYNAMIC"
    if command == "LINE":
        return "LINE"
    if command == "RECOLOR":
        return "RECOLOR"
    if command in ("SRB", "PMP2", "PMP"):
        return "Sprites"
    return "Other"


def index_source_entries(text: str) -> tuple[SourceEntry, ...]:
    """Index logical statements, keeping multiline declarations together.

    A comment-only line is a filterable item; comments inside an unfinished
    statement stay with that statement so navigation never lands in a fragment.
    Blank lines stay in the original editor, but are omitted from the results.
    Handles incomplete source conservatively, breaking at the next declaration.
    """
    lines = text.splitlines()
    entries = []
    line = 0
    while line < len(lines):
        start = line
        raw = lines[line]
        if not raw.strip():
            line += 1
            continue
        category = classify_statement(raw)
        if category == "Comments (%)":
            entries.append(SourceEntry(start, start, category, raw.strip()[:240]))
            line += 1
            continue

        preview = raw.strip()
        complete = _finished(raw)
        # Only named declarations can consume continuation lines; a header
        # or malformed line remains an individual navigable entry.
        if _START.match(raw) and not complete:
            while line + 1 < len(lines):
                next_raw = lines[line + 1]
                if _START.match(next_raw):
                    break
                line += 1
                if _finished(next_raw):
                    break
        if line > start:
            preview += f" … ({line - start + 1} lines)"
        entries.append(SourceEntry(start, line, category, preview[:240]))
        line += 1
    return tuple(entries)
