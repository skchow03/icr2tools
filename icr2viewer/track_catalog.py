"""Utilities for discovering tracks within an ICR2 installation."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import List, Optional


TNAME_PATTERN = re.compile(r"^\s*TNAME\s+(.+)$", re.IGNORECASE)
TLENGTH_PATTERN = re.compile(r"^\s*TLEN(?:GTH)?\s+([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)


@dataclass
class TrackMetadata:
    """Minimal track metadata discovered from the installation."""

    folder_name: str
    path: str
    display_name: str
    txt_length_miles: Optional[float] = None


class TrackDiscoveryError(RuntimeError):
    """Raised when tracks cannot be located for the supplied directory."""


def find_tracks_folder(icr2_dir: str) -> str:
    """Locate the TRACKS directory for an IndyCar Racing II installation."""

    if not icr2_dir or not os.path.isdir(icr2_dir):
        raise TrackDiscoveryError(f"ICR2 directory not found: {icr2_dir}")

    candidates = []
    for entry in os.listdir(icr2_dir):
        if entry.lower() == "tracks":
            candidate = os.path.join(icr2_dir, entry)
            if os.path.isdir(candidate):
                candidates.append(candidate)

    if not candidates:
        raise TrackDiscoveryError("TRACKS directory not found inside the ICR2 folder")

    # Prefer the first alphabetically for deterministic behaviour.
    candidates.sort()
    return candidates[0]


def _parse_track_txt(track_dir: str, folder_name: str) -> tuple[str, Optional[float]]:
    txt_path = os.path.join(track_dir, f"{folder_name}.TXT")
    display_name = folder_name
    length_miles: Optional[float] = None

    if not os.path.isfile(txt_path):
        return display_name, length_miles

    try:
        with open(txt_path, "r", encoding="latin-1", errors="ignore") as f:
            for line in f:
                name_match = TNAME_PATTERN.search(line)
                if name_match:
                    display_name = name_match.group(1).strip()
                    continue

                length_match = TLENGTH_PATTERN.search(line)
                if length_match:
                    try:
                        length_miles = float(length_match.group(1))
                    except ValueError:
                        length_miles = None
    except Exception:
        # Fallback to folder name if file can't be parsed.
        display_name = folder_name
        length_miles = None

    return display_name or folder_name, length_miles


def discover_tracks(icr2_dir: str) -> List[TrackMetadata]:
    """Return available track directories for the supplied ICR2 installation."""

    tracks_dir = find_tracks_folder(icr2_dir)
    entries: List[TrackMetadata] = []

    for entry in os.listdir(tracks_dir):
        path = os.path.join(tracks_dir, entry)
        if not os.path.isdir(path):
            continue
        folder_name = entry
        display_name, length_miles = _parse_track_txt(path, folder_name)

        # Only consider tracks that contain TRK or DAT assets.
        try:
            assets = os.listdir(path)
        except OSError:
            continue

        has_assets = any(name.lower().endswith((".trk", ".dat")) for name in assets)
        if not has_assets:
            continue

        entries.append(
            TrackMetadata(
                folder_name=folder_name,
                path=path,
                display_name=display_name,
                txt_length_miles=length_miles,
            )
        )

    entries.sort(key=lambda item: item.display_name.lower())
    return entries
