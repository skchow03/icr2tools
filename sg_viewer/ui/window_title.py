from __future__ import annotations

from pathlib import Path


def build_window_title(
    *,
    path: Path | None,
    is_dirty: bool,
    is_untitled: bool = False,
) -> str:
    if is_untitled:
        name = "Untitled"
    elif path is not None:
        name = path.name
    else:
        return "SG CREATE"

    dirty_marker = "*" if is_dirty else ""
    return f"{name}{dirty_marker} — SG CREATE"
