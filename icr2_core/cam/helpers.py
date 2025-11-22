"""Utility helpers for loading IndyCar Racing 2 camera definitions."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence

from .binutils import chunk, read_int32_bytes, read_int32_file, write_int32_file


@dataclass
class Type6CameraParameters:
    """Additional parameters available for type 6 cameras."""

    middle_point: int
    start_point: int
    start_zoom: int
    middle_point_zoom: int
    end_point: int
    end_zoom: int


@dataclass
class Type7CameraParameters:
    """Additional parameters available for type 7 cameras."""

    z_axis_rotation: int
    vertical_rotation: int
    tilt: int
    zoom: int
    unknown1: int
    unknown2: int
    unknown3: int
    unknown4: int


@dataclass
class CameraPosition:
    """Simple representation of a camera defined inside a CAM file."""

    camera_type: int
    index: int
    x: int
    y: int
    z: int
    type6: Type6CameraParameters | None = None
    type7: Type7CameraParameters | None = None
    raw_values: tuple[int, ...] | None = None


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


def _parse_cam_positions(values: Sequence[int]) -> List[CameraPosition]:
    """Parse the integer contents of a CAM file into camera positions."""

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
            type6_params = None
            type7_params = None
            if camera_type == 6 and len(row) >= 9:
                type6_params = Type6CameraParameters(
                    middle_point=row[0],
                    start_point=row[4],
                    start_zoom=row[5],
                    middle_point_zoom=row[6],
                    end_point=row[7],
                    end_zoom=row[8],
                )
            if camera_type == 7 and len(row) >= 8:
                type7_params = Type7CameraParameters(
                    z_axis_rotation=row[4],
                    vertical_rotation=row[5],
                    tilt=row[6],
                    zoom=row[7],
                    unknown1=row[8] if len(row) > 8 else 0,
                    unknown2=row[9] if len(row) > 9 else 0,
                    unknown3=row[10] if len(row) > 10 else 0,
                    unknown4=row[11] if len(row) > 11 else 0,
                )
            positions.append(
                CameraPosition(
                    camera_type=camera_type,
                    index=index,
                    x=row[1],
                    y=row[2],
                    z=row[3],
                    type6=type6_params,
                    type7=type7_params,
                    raw_values=tuple(row),
                )
            )

    return positions


def load_cam_positions(path: str | Path) -> List[CameraPosition]:
    """Parse a `.cam` binary and return the relevant camera positions."""

    values = read_int32_file(_normalize_path(path))
    return _parse_cam_positions(values)


def load_cam_positions_bytes(data: bytes) -> List[CameraPosition]:
    """Parse a `.cam` payload loaded directly into memory."""

    values = read_int32_bytes(data)
    return _parse_cam_positions(values)


def _parse_scr_segments(values: Sequence[int]) -> List[CameraSegmentRange]:
    """Parse the integer contents of an SCR file into segment ranges."""

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


def load_scr_segments(path: str | Path) -> List[CameraSegmentRange]:
    """Parse `.scr` binary files into segment ranges per camera."""

    values = read_int32_file(_normalize_path(path))
    return _parse_scr_segments(values)


def load_scr_segments_bytes(data: bytes) -> List[CameraSegmentRange]:
    """Parse `.scr` payloads loaded directly into memory."""

    values = read_int32_bytes(data)
    return _parse_scr_segments(values)


def _serialize_cam_rows(cameras: Sequence[CameraPosition]) -> List[int]:
    grouped: dict[int, list[CameraPosition]] = {6: [], 2: [], 7: []}
    for camera in cameras:
        grouped.setdefault(camera.camera_type, []).append(camera)
    values: List[int] = []
    for camera_type, width in ((6, 9), (2, 9), (7, 12)):
        entries = sorted(grouped.get(camera_type, []), key=lambda c: c.index)
        values.append(len(entries))
        for camera in entries:
            row = list(camera.raw_values) if camera.raw_values else []
            if len(row) < width:
                row.extend([0] * (width - len(row)))
            row[1:4] = [camera.x, camera.y, camera.z]
            if camera_type == 6 and camera.type6 is not None:
                row[0] = camera.type6.middle_point
                row[4] = camera.type6.start_point
                row[5] = camera.type6.start_zoom
                row[6] = camera.type6.middle_point_zoom
                row[7] = camera.type6.end_point
                row[8] = camera.type6.end_zoom
            if camera_type == 7 and camera.type7 is not None:
                row[4] = camera.type7.z_axis_rotation
                row[5] = camera.type7.vertical_rotation
                row[6] = camera.type7.tilt
                row[7] = camera.type7.zoom
                row[8] = camera.type7.unknown1
                row[9] = camera.type7.unknown2
                row[10] = camera.type7.unknown3
                row[11] = camera.type7.unknown4
            values.extend(row[:width])
    return values


def write_cam_positions(path: str | Path, cameras: Sequence[CameraPosition]) -> None:
    """Write camera definitions to a `.cam` file."""

    rows = _serialize_cam_rows(cameras)
    write_int32_file(_normalize_path(path), rows)


def _serialize_scr_segments(views: Sequence["CameraViewListing"]) -> List[int]:
    if not views:
        return [0]
    sorted_views = sorted(views, key=lambda v: v.view)
    values: List[int] = [len(sorted_views)]
    values.extend(len(view.entries) for view in sorted_views)
    for view in sorted_views:
        for entry in view.entries:
            mark = entry.mark
            if mark is None:
                mark = entry.camera_type
            if mark is None:
                mark = 0

            camera_index = entry.type_index
            if camera_index is None:
                camera_index = entry.camera_index
            if camera_index is None:
                camera_index = 0
            start = entry.start_dlong if entry.start_dlong is not None else 0
            end = entry.end_dlong if entry.end_dlong is not None else 0
            values.extend([mark, camera_index, start, end])
    return values


def write_scr_segments(path: str | Path, views: Sequence["CameraViewListing"]) -> None:
    """Write camera segment mappings to a `.scr` file."""

    rows = _serialize_scr_segments(views)
    write_int32_file(_normalize_path(path), rows)
