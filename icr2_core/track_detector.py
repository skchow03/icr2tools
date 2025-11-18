"""Track detection helpers used by ``MemoryReader``."""
from __future__ import annotations

import os
import re
from typing import Callable, List, Optional, Tuple


class TrackDetector:
    """Encapsulate WINDY/DOS track-name detection (with caching)."""

    def __init__(self, mem, cfg, error_cls: Callable[[str], Exception]):
        self._mem = mem
        self._cfg = cfg
        self._error_cls = error_cls
        self._cached_tracks: Optional[List[Tuple[str, str]]] = None
        self._cached_index: Optional[int] = None

    def read_current_track(self) -> str:
        version = getattr(self._cfg, "version", "").upper()
        if version == "WINDY101":
            return self._read_windy_track()
        return self._read_dos_track()

    # --- private helpers -------------------------------------------------

    def _read_windy_track(self) -> str:
        idx_raw = self._mem.read(0x527D58, "i32")
        if idx_raw is None:
            raise self._error_cls("track index missing at 0x527D58")
        idx = int(idx_raw)

        if (
            self._cached_tracks is not None
            and self._cached_index == idx
        ):
            try:
                return self._cached_tracks[idx][0]
            except Exception:
                pass

        exe_path = getattr(self._cfg, "game_exe", "")
        if not exe_path:
            raise self._error_cls("game_exe not set in settings.ini")

        tracks_root = os.path.join(os.path.dirname(exe_path), "TRACKS")
        if not os.path.isdir(tracks_root):
            raise self._error_cls(f"TRACKS folder not found: {tracks_root}")

        tname_pattern = re.compile(r"^\s*TNAME\s+(.+)$", re.IGNORECASE | re.MULTILINE)
        entries: List[Tuple[str, str]] = []

        for sub in os.listdir(tracks_root):
            sub_path = os.path.join(tracks_root, sub)
            if not os.path.isdir(sub_path):
                continue
            txt_path = os.path.join(sub_path, f"{sub}.TXT")
            if not os.path.isfile(txt_path):
                continue
            try:
                with open(txt_path, "r", errors="ignore") as handle:
                    txt = handle.read()
                match = tname_pattern.search(txt)
                if not match:
                    continue
                display_name = match.group(1).strip()
                entries.append((sub, display_name))
            except Exception:
                continue

        if not entries:
            raise self._error_cls("no valid tracks found under TRACKS folder")

        entries.sort(key=lambda item: item[1].lower())
        if not (0 <= idx < len(entries)):
            raise self._error_cls(f"track index {idx} out of range")

        self._cached_tracks = entries
        self._cached_index = idx
        return entries[idx][0]

    def _read_dos_track(self) -> str:
        raw = self._mem.read(self._cfg.current_track_addr, 'bytes', count=256)
        if raw is None:
            raise self._error_cls(f"no track name at 0x{self._cfg.current_track_addr:X}")

        blob = bytes(raw) if isinstance(raw, (bytes, bytearray)) else bytes(raw or b"")
        name_raw = blob.split(b'\x00', 1)[0]
        return name_raw.decode('ascii', errors='ignore').strip()
