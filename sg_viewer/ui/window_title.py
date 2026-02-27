from __future__ import annotations

from pathlib import Path


def build_window_title(
    *,
    path: Path | None,
    project_path: Path | None = None,
    is_dirty: bool,
    is_untitled: bool = False,
) -> str:
    if is_untitled:
        name = "Untitled"
    elif path is not None:
        project_name = project_path.name if project_path is not None else None
        if project_name is not None:
            name = f"{project_name} [{path.name}]"
        else:
            name = path.name
    else:
        return "SG CREATE"

    dirty_marker = "*" if is_dirty else ""
    return f"{name}{dirty_marker} — SG CREATE"
