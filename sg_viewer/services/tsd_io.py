from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TrackSurfaceDetailLine:
    color_index: int
    width_500ths: int
    start_dlong: int
    start_dlat: int
    end_dlong: int
    end_dlat: int


@dataclass(frozen=True)
class TrackSurfaceDetailFile:
    lines: tuple[TrackSurfaceDetailLine, ...]


def serialize_tsd(detail_file: TrackSurfaceDetailFile) -> str:
    rows = [
        (
            f"Detail: {line.color_index} {line.width_500ths} "
            f"{line.start_dlong} {line.start_dlat} {line.end_dlong} {line.end_dlat}"
        )
        for line in detail_file.lines
    ]
    return "\n".join(rows) + ("\n" if rows else "")
