"""Safe N3 source-symbol renaming without changing comments or resource names.

Only authored declaration labels are rename targets. Reference replacement
recognizes complete N3 identifier tokens outside comments and quoted strings.
No source geometry/binary data is written by this module.
"""
from __future__ import annotations

import re

NAME = r"[A-Za-z_][A-Za-z_0-9-]*"
DECLARATION = re.compile(r"^[ \t]*(?P<name>" + NAME + r")[ \t]*:")
TOKEN = re.compile(
    r'(?P<comment>%[^\n]*)|(?P<string>"[^"\n]*")|'
    r'(?P<identifier>' + NAME + r')', re.M)
NAME_ONLY = re.compile(NAME + r"\Z")
# These are N3 grammar tokens and field names, not user-defined pointer names.
KEYWORDS = frozenset((
    "3D", "VERSION", "NIL", "POLY", "LINE", "LIST", "FACE",
    "FACE2", "BSPF", "BSPA", "BSP2", "BSPN", "MATERIAL",
    "GROUP", "MIP", "SWITCH", "DISTANCE", "DYNAMIC", "EXTERN",
    "SUPEROBJ", "PMP2", "SRB", "RECOLOR", "DYNO", "DATA", "T",
    "U", "V",
))


def _line(text: str, number: int) -> str | None:
    if number < 0:
        return None
    # Qt edits affect one line at a time in the normal rename workflow.
    lines = text.split("\n")
    return lines[number] if number < len(lines) else None


def declaration_label(text: str, line: int) -> str | None:
    row = _line(text, line)
    if row is None:
        return None
    match = DECLARATION.match(row)
    return match.group("name") if match else None


def edited_declaration_label(before: str, after: str,
                             line: int) -> str | None:
    """Return previous label when only the declaration token was edited.

    A temporarily empty label returns the old name too; the editor can
    remember it until a valid replacement is fully typed. Changes to the
    statement body, comments or unrelated rows are not rename operations.
    """
    old = _line(before, line)
    new = _line(after, line)
    if old is None or new is None or old == new:
        return None
    orig = DECLARATION.match(old)
    if not orig:
        return None
    old_name = orig.group("name")
    if old_name.upper() in KEYWORDS:
        return None
    fresh = DECLARATION.match(new)
    if fresh:
        if old_name == fresh.group("name"):
            return None
        if (old[:orig.start("name")] == new[:fresh.start("name")] and
                old[orig.end("name"):] == new[fresh.end("name"):]):
            return old_name
        return None
    # Entire name selected and deleted: preserve the original label until
    # replacement characters are entered.
    if (new.startswith(old[:orig.start("name")]) and
            new[len(old[:orig.start("name")]):] ==
            old[orig.end("name"):]):
        return old_name
    return None


def reference_spans(source: str, old: str, new: str) -> list[tuple[int, int]]:
    """Find exact source reference tokens, excluding N3 syntax and comments.

    The renamed declaration is already named "new" in source. Refuse to
    cascade changes when either name collides with another declaration,
    or when names would overlap N3 language keywords.
    """
    if (not NAME_ONLY.fullmatch(old) or not NAME_ONLY.fullmatch(new)
            or old == new or old.upper() in KEYWORDS
            or new.upper() in KEYWORDS):
        return []
    declarations = [
        (m.group("name"), m.start("name"), m.end("name"))
        for m in re.finditer(r"(?m)^[ \t]*(?P<name>" + NAME + r")[ \t]*:",
                             source)]
    names = [name for name, _, _ in declarations]
    if names.count(new) != 1 or old in names:
        return []
    declaration_spans = {(start, end) for _, start, end in declarations}
    positions = []
    for match in TOKEN.finditer(source):
        if match.lastgroup != "identifier" or match.group() != old:
            continue
        span = match.span()
        if span in declaration_spans:
            continue
        # Preserve N3 named-parameter names such as c=<color> and
        # quoted MIP/PMP/EXTERN resources. For normal labels this is a
        # conservative refusal rather than a potentially corrupting edit.
        if source[span[1]:].lstrip(" \t").startswith("="):
            continue
        positions.append(span)
    return positions



def plan_pointer_rename(source: str, line: int, new: str,
                        *, update_references: bool = True
                        ) -> tuple[str, list[tuple[int, int, str]]]:
    """Return (old name, original-source spans) for one atomic F2 rename.

    Every span is expressed in Python string offsets of the unchanged source.
    The declaration's command, whitespace, comments, punctuation and all
    other declarations are left byte-for-byte as authored. References are
    changed only when requested; invalid or ambiguous renames raise ValueError.
    """
    rows = source.splitlines(keepends=True)
    if not 0 <= line < len(rows):
        raise ValueError("Select an N3 declaration before pressing F2.")
    match = DECLARATION.match(rows[line])
    if match is None:
        raise ValueError("The selected line is not a named N3 declaration.")
    old = match.group("name")
    if not NAME_ONLY.fullmatch(new) or new.upper() in KEYWORDS:
        raise ValueError(
            "A pointer name must begin with a letter or underscore and "
            "contain only letters, digits, underscores, or hyphens; "
            "N3 keywords are not valid names.")
    if old.upper() in KEYWORDS:
        raise ValueError(f"Cannot rename reserved N3 keyword {old!r}.")
    if new == old:
        return old, []

    declaration_names = [
        item.group("name")
        for item in re.finditer(
            r"(?m)^[ \t]*(?P<name>" + NAME + r")[ \t]*:", source)
    ]
    if declaration_names.count(old) != 1:
        raise ValueError(
            f"Pointer {old!r} is ambiguous because it has multiple declarations.")
    if new in declaration_names:
        raise ValueError(f"A declaration named {new!r} already exists.")

    start = sum(len(row) for row in rows[:line]) + match.start("name")
    end = start + len(old)
    edits = [(start, end, new)]
    if update_references:
        changed = source[:start] + new + source[end:]
        delta = len(new) - len(old)
        for first, last in reference_spans(changed, old, new):
            # Convert positions in hypothetical renamed text back to the
            # original document so one descending edit block can replace
            # everything together without shifting earlier cursor positions.
            if first >= start + len(new):
                first -= delta
                last -= delta
            edits.append((first, last, new))
    return old, sorted(edits, key=lambda item: item[0], reverse=True)


def qt_utf16_offset(source: str, python_offset: int) -> int:
    """Convert Python code-point offsets to QTextCursor UTF-16 positions."""
    return len(source[:python_offset].encode("utf-16-le")) // 2
