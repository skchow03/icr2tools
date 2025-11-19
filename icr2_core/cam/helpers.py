"""Utility helpers for loading IndyCar Racing 2 camera definitions."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence

from .binutils import chunk, read_int32_file


@dataclass
class CameraPosition:
    """Simple representation of a camera defined inside a CAM file."""

    camera_type: int
    index: int
    x: int
    y: int
    z: int


@dataclass
class CameraSegmentRange:
    """Mapping between SCR entries and camera ids across the track."""

    view: int
    mark: int
    camera_id: int
    start_dlong: int
    end_dlong: int


def _normalize_path(path: str | Path) -> str:
    path = Path(path)
    return str(path.expanduser().resolve())


def load_cam_positions(path: str | Path) -> List[CameraPosition]:
    """Parse a `.cam` binary and return the relevant camera positions."""

    values = read_int32_file(_normalize_path(path))
    if not values:
        return []

    cursor = 0
    total = len(values)
    positions: List[CameraPosition] = []

    def _chunk_rows(count: int, width: int) -> Sequence[Sequence[int]]:
        nonlocal cursor
        end = min(total, cursor + count * width)
        data = values[cursor:end]
        cursor = end
        return chunk(data, width)

    def _read_count() -> int:
        nonlocal cursor
        if cursor >= total:
            return 0
        count = values[cursor]
        cursor += 1
        return count

    for camera_type, width in ((6, 9), (2, 9), (7, 12)):
        count = _read_count()
        rows = _chunk_rows(count, width)
        for index, row in enumerate(rows):
            if len(row) < 4:
                continue
            positions.append(
                CameraPosition(
                    camera_type=camera_type,
                    index=index,
                    x=row[1],
                    y=row[2],
                    z=row[3],
                )
            )

    return positions


def load_scr_segments(path: str | Path) -> List[CameraSegmentRange]:
    """Parse `.scr` binary files into segment ranges per camera."""

    values = read_int32_file(_normalize_path(path))
    if not values:
        return []

    cursor = 0
    total = len(values)
    segments: List[CameraSegmentRange] = []

    num_views = values[cursor]
    cursor += 1
    counts: List[int] = []
    for _ in range(num_views):
        if cursor >= total:
            break
        counts.append(values[cursor])
        cursor += 1

    for view_index, cam_count in enumerate(counts, start=1):
        for _ in range(cam_count):
            if cursor + 4 > total:
                break
            mark, cam_id, start_dlong, end_dlong = values[cursor : cursor + 4]
            cursor += 4
            segments.append(
                CameraSegmentRange(
                    view=view_index,
                    mark=mark,
                    camera_id=cam_id,
                    start_dlong=start_dlong,
                    end_dlong=end_dlong,
                )
            )

    return segments
