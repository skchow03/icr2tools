"""Read-only N3 pointer navigation shared by keyboard and Ctrl-click.

Resolve exact case-sensitive declaration symbols, not quoted filenames,
comments, grammar keywords, assignment names, or declaration definitions.
This is independent of compilation so it also works while source is edited.
"""
from __future__ import annotations

from dataclasses import dataclass

from gpu_viewer.source_rename import DECLARATION, KEYWORDS, TOKEN


@dataclass(frozen=True)
class PointerReference:
    name: str
    target_line: int


def declaration_lines(source: str) -> dict[str, int]:
    """Map unambiguous named declarations to zero-based original lines.

    Duplicate declaration labels are left unresolved rather than selecting an
    arbitrary definition. Generated binary _offset labels work as normal.
    """
    result = {}
    ambiguous = set()
    for number, row in enumerate(source.splitlines()):
        match = DECLARATION.match(row)
        if match is None:
            continue
        name = match.group("name")
        if name.upper() in KEYWORDS:
            continue
        if name in result:
            ambiguous.add(name)
        else:
            result[name] = number
    for name in ambiguous:
        result.pop(name, None)
    return result


def pointer_at_column(row: str, column: int,
                      declarations: dict[str, int], *,
                      include_end: bool = True) -> PointerReference | None:
    """Find an N3 reference under/at the end of a caret or mouse position.

    The lexer excludes comments and quoted resource names even when they
    contain punctuation or look like real N3 pointers. Do not interpret the
    left side of named assignments (such as MIP= or c=) as a pointer.
    """
    if column < 0 or column > len(row):
        return None
    definition = DECLARATION.match(row)
    candidates = []
    for token in TOKEN.finditer(row):
        if token.lastgroup != "identifier":
            continue
        start, end = token.span()
        if not (start <= column < end or
                include_end and column == end):
            continue
        name = token.group()
        if (name not in declarations or name.upper() in KEYWORDS or
                definition is not None and
                (start, end) == definition.span("name")):
            continue
        if row[end:].lstrip(" \t").startswith("="):
            continue
        candidates.append((start <= column < end, end, name))
    if not candidates:
        return None
    # A caret between adjacent tokens favors the token that starts here,
    # otherwise a caret just after a reference still works with F12.
    candidates.sort(reverse=True)
    name = candidates[0][2]
    return PointerReference(name, declarations[name])
