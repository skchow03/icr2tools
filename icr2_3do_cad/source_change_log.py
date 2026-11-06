"""Summaries for source modifications made automatically by the .3D editor.

The authoritative N3 document and its undo history are owned by SourcePane.
This module only describes known replacement spans; it never modifies source.
"""
from __future__ import annotations

MAX_DETAILS_PER_OPERATION = 30


def format_rename_event(source, old, new, spans, *, action, declaration_line):
    """Return a compact log entry followed by reference-level source locations.

    Spans refer to the unchanged source at the instant the references were
    rewritten (F2: before renaming; live auto-rename: after declaration rename).
    Walking positions in ascending order avoids O(file size x references)
    newline counting on large generated tracks.
    """
    positions = sorted(start for start, *_ in spans)
    summary = (
        f"{action}: {old} → {new} (declaration line {declaration_line + 1}; "
        f"{len(positions):,} reference{'s' if len(positions) != 1 else ''} updated)"
    )
    if not positions:
        return [summary]
    lines = [summary]
    current = 0
    line_number = 1
    for start in positions[:MAX_DETAILS_PER_OPERATION]:
        if start < current:
            continue
        line_number += source.count("\n", current, start)
        current = start
        lines.append(f"  line {line_number}: {old} → {new}")
    remaining = len(positions) - min(len(positions), MAX_DETAILS_PER_OPERATION)
    if remaining:
        lines.append(f"  … {remaining:,} additional references updated")
    return lines
