"""Helpers for locating LP files in track folders."""
from __future__ import annotations

from pathlib import Path


def resolve_lp_path(track_folder: Path, lp_name: str) -> Path | None:
    """Find an LP file for the given name, ignoring filename case."""
    candidate = track_folder / f"{lp_name}.LP"
    if candidate.exists():
        return candidate
    if not track_folder.exists():
        return None
    target = f"{lp_name}.LP".lower()
    for entry in track_folder.iterdir():
        if entry.is_file() and entry.name.lower() == target:
            return entry
    return None
