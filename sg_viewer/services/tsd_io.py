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


def parse_tsd(content: str) -> TrackSurfaceDetailFile:
    lines: list[TrackSurfaceDetailLine] = []
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue
        prefix, sep, payload = stripped.partition(":")
        if sep != ":" or prefix.strip().lower() != "detail":
            raise ValueError(f"Line {line_number}: expected 'Detail:' prefix.")
        parts = payload.strip().split()
        if len(parts) != 6:
            raise ValueError(
                f"Line {line_number}: expected 6 integer fields after 'Detail:'."
            )
        try:
            values = [int(value) for value in parts]
        except ValueError as exc:
            raise ValueError(f"Line {line_number}: all fields must be integers.") from exc
        lines.append(TrackSurfaceDetailLine(*values))
    return TrackSurfaceDetailFile(lines=tuple(lines))
