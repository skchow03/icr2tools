"""Read-only navigation from an N3 pointer use to its declaration.

Navigation deliberately uses current source text, not compiled offsets: it
works while a newly edited .3D document is still awaiting recompilation.
N3 identifier tokens are recognized outside comments and quoted resources.
"""
from __future__ import annotations

import re

from source_rename import KEYWORDS, TOKEN, qt_utf16_offset


_DECLARATION = re.compile(
    r"^[ \t]*(?P<label>[A-Za-z_][A-Za-z_0-9-]*)[ \t]*:")


def declaration_lines(source: str) -> dict[str, int]:
    """Map unique source pointer names to their zero-based declaration rows.

    Ambiguous duplicate declarations are intentionally not navigable until
    corrected. Unlike the GPU inspection index, include every N3 command
    type (LIST, FACE, BSP, MATERIAL, DYNAMIC, POLY and vertex definitions).
    """
    found = {}
    ambiguous = set()
    for line_no, line in enumerate(source.splitlines()):
        match = _DECLARATION.match(line)
        if match is None:
            continue
        name = match.group("label")
        if name in found:
            ambiguous.add(name)
        else:
            found[name] = line_no
    for name in ambiguous:
        found.pop(name, None)
    return found


def referenced_pointer_at(line: str, utf16_column: int,
                          declarations: dict[str, int]) -> str | None:
    """Resolve a click caret within a real pointer token, not syntax or text.

    QTextCursor counts UTF-16 code units, not Python code points. The caller
    additionally verifies that the click falls within the token's actual
    on-screen bounding rectangle, so clicks in trailing whitespace do not
    follow the nearest word.
    """
    if utf16_column < 0 or not declarations:
        return None
    declaration = _DECLARATION.match(line)
    for match in TOKEN.finditer(line):
        if match.lastgroup != "identifier":
            continue
        name = match.group()
        if name not in declarations or name.upper() in KEYWORDS:
            continue
        # Clicking the definition is not a reference and must not push a
        # no-op history entry.
        if (declaration is not None and
                match.start() == declaration.start("label") and
                match.end() == declaration.end("label")):
            continue
        # Field/parameter keys such as T= or c= are not pointer uses.
        if line[match.end():].lstrip(" \t").startswith("="):
            continue
        begin = qt_utf16_offset(line, match.start())
        end = qt_utf16_offset(line, match.end())
        if begin <= utf16_column <= end:
            return name
    return None
