from __future__ import annotations

from dataclasses import dataclass
import logging
import math
import re

from sg_viewer.model.dlong_mapping import dlong_to_section_position
from sg_viewer.model.preview_fsection import PreviewFSection
from sg_viewer.model.sg_model import SectionPreview


_MARK_HEADER = "MARK_V1"
_POS_RE = re.compile(r"^(?P<section>-?\d+)\s+(?P<fraction>-?(?:\d+(?:\.\d*)?|\.\d+))$")
_ENTRY_RE = re.compile(
    r'^(?P<name>[^:]+):\s*Boundary\s+(?P<boundary>\d+)\s+"(?P<mip>[^"]+)"\s*<\s*(?P<u1>-?\d+)\s*,\s*(?P<v1>-?\d+)\s*>\s*-\s*<\s*(?P<u2>-?\d+)\s*,\s*(?P<v2>-?\d+)\s*>$'
)
_END_RE = re.compile(r"^End\s+(?P<name>.+)$")


@dataclass(frozen=True)
class MarkTrackPosition:
    section: int
    fraction: float


@dataclass(frozen=True)
class MarkUvRect:
    upper_left_u: int
    upper_left_v: int
    lower_right_u: int
    lower_right_v: int


@dataclass(frozen=True)
class MarkBoundaryEntry:
    pointer_name: str
    boundary_id: int
    mip_name: str
    uv_rect: MarkUvRect
    start: MarkTrackPosition
    end: MarkTrackPosition


@dataclass(frozen=True)
class MarkFile:
    entries: tuple[MarkBoundaryEntry, ...]
    version: str = _MARK_HEADER


@dataclass(frozen=True)
class MarkTextureSpec:
    mip_name: str
    uv_rect: MarkUvRect


def _strip_comment(line: str) -> str:
    return line.split("##", 1)[0].strip()


def _parse_position(line: str, *, line_number: int) -> MarkTrackPosition:
    match = _POS_RE.match(line)
    if not match:
        raise ValueError(f"Expected section/fraction at line {line_number}: {line!r}")
    section = int(match.group("section"))
    fraction = float(match.group("fraction"))
    if fraction < 0.0 or fraction > 1.0:
        raise ValueError(f"Track fraction must be in [0, 1] at line {line_number}, got {fraction}")
    return MarkTrackPosition(section=section, fraction=fraction)


def parse_mrk_text(text: str) -> MarkFile:
    lines = [_strip_comment(raw) for raw in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        raise ValueError("MRK file is empty")
    if lines[0] != _MARK_HEADER:
        raise ValueError(f"Expected MRK header {_MARK_HEADER!r}, got {lines[0]!r}")

    entries: list[MarkBoundaryEntry] = []
    seen_names: set[str] = set()
    index = 1

    while index < len(lines):
        start = _parse_position(lines[index], line_number=index + 1)
        if index + 1 >= len(lines):
            raise ValueError("Unexpected end of file after start position")
        entry_line = lines[index + 1]
        entry_match = _ENTRY_RE.match(entry_line)
        if not entry_match:
            raise ValueError(f"Expected boundary entry at line {index + 2}: {entry_line!r}")

        pointer_name = entry_match.group("name").strip()
        if pointer_name in seen_names:
            raise ValueError(f"Duplicate pointer name {pointer_name!r}")
        seen_names.add(pointer_name)

        if index + 3 >= len(lines):
            raise ValueError(f"Unexpected end of file while parsing entry {pointer_name!r}")
        end = _parse_position(lines[index + 2], line_number=index + 3)
        end_match = _END_RE.match(lines[index + 3])
        if not end_match:
            raise ValueError(f"Expected entry terminator at line {index + 4}: {lines[index + 3]!r}")
        end_name = end_match.group("name").strip()
        if end_name != pointer_name:
            raise ValueError(
                f"Entry terminator mismatch at line {index + 4}: expected {pointer_name!r}, got {end_name!r}"
            )

        entries.append(
            MarkBoundaryEntry(
                pointer_name=pointer_name,
                boundary_id=int(entry_match.group("boundary")),
                mip_name=entry_match.group("mip"),
                uv_rect=MarkUvRect(
                    upper_left_u=int(entry_match.group("u1")),
                    upper_left_v=int(entry_match.group("v1")),
                    lower_right_u=int(entry_match.group("u2")),
                    lower_right_v=int(entry_match.group("v2")),
                ),
                start=start,
                end=end,
            )
        )

        index += 4

    return MarkFile(entries=tuple(entries))


def _format_fraction(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def serialize_mrk(mark_file: MarkFile) -> str:
    lines = [mark_file.version]
    for entry in mark_file.entries:
        lines.append(f"{entry.start.section} {_format_fraction(entry.start.fraction)}")
        lines.append(
            f'{entry.pointer_name}: Boundary {entry.boundary_id} "{entry.mip_name}" '
            f"<{entry.uv_rect.upper_left_u},{entry.uv_rect.upper_left_v}> - "
            f"<{entry.uv_rect.lower_right_u},{entry.uv_rect.lower_right_v}>"
        )
        lines.append(f"{entry.end.section} {_format_fraction(entry.end.fraction)}")
        lines.append(f"End {entry.pointer_name}")
    return "\n".join(lines) + "\n"


_BOUNDARY_TYPES = {7, 8}
_DEFAULT_MARK_WALL_LENGTH = 14.0 * 6000.0
_DEFAULT_BOUNDARY_MATCH_TOLERANCE = 2.0 * 6000.0
_MIN_BOUNDARY_SAMPLES = 24

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class _BoundarySignature:
    surface_type: int
    type2: int
    avg_dlat: float
    dlat_range: tuple[float, float]


@dataclass
class _BoundaryTrack:
    boundary_id: int
    surface_type: int
    type2: int
    last_avg_dlat: float


def _boundary_rows_for_section(fsects: list[PreviewFSection]) -> list[PreviewFSection]:
    rows = [fsect for fsect in fsects if int(fsect.surface_type) in _BOUNDARY_TYPES]
    rows.sort(
        key=lambda fsect: (
            min(float(fsect.start_dlat), float(fsect.end_dlat)),
            max(float(fsect.start_dlat), float(fsect.end_dlat)),
        )
    )
    return rows


def _flipped_u(uv_rect: MarkUvRect) -> MarkUvRect:
    return MarkUvRect(
        upper_left_u=uv_rect.lower_right_u,
        upper_left_v=uv_rect.upper_left_v,
        lower_right_u=uv_rect.upper_left_u,
        lower_right_v=uv_rect.lower_right_v,
    )


def _average_dlat(boundary: PreviewFSection) -> float:
    return (float(boundary.start_dlat) + float(boundary.end_dlat)) * 0.5


def _boundary_signature(boundary: PreviewFSection) -> _BoundarySignature:
    start_dlat = float(boundary.start_dlat)
    end_dlat = float(boundary.end_dlat)
    return _BoundarySignature(
        surface_type=int(boundary.surface_type),
        type2=int(boundary.type2),
        avg_dlat=(start_dlat + end_dlat) * 0.5,
        dlat_range=(min(start_dlat, end_dlat), max(start_dlat, end_dlat)),
    )


def _polyline_length(points: list[tuple[float, float]]) -> float:
    total = 0.0
    for index in range(len(points) - 1):
        x1, y1 = points[index]
        x2, y2 = points[index + 1]
        total += math.hypot(x2 - x1, y2 - y1)
    return total


def _sample_polyline_with_tangent(
    points: list[tuple[float, float]],
    distance_along: float,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    if len(points) < 2:
        return None
    remaining = max(0.0, float(distance_along))
    for index in range(len(points) - 1):
        x1, y1 = points[index]
        x2, y2 = points[index + 1]
        dx = x2 - x1
        dy = y2 - y1
        seg_len = math.hypot(dx, dy)
        if seg_len <= 1e-9:
            continue
        if remaining <= seg_len:
            t = remaining / seg_len
            return ((x1 + dx * t, y1 + dy * t), (dx, dy))
        remaining -= seg_len
    x1, y1 = points[-2]
    x2, y2 = points[-1]
    return ((x2, y2), (x2 - x1, y2 - y1))


def _boundary_polyline(section: SectionPreview, boundary: PreviewFSection) -> list[tuple[float, float]]:
    centerline = [(float(point[0]), float(point[1])) for point in section.polyline if point is not None]
    if len(centerline) < 2:
        return []

    centerline_length = _polyline_length(centerline)
    if centerline_length <= 1e-9:
        return []

    sample_count = max(_MIN_BOUNDARY_SAMPLES, len(centerline) * 3)
    boundary_points: list[tuple[float, float]] = []

    for sample_index in range(sample_count + 1):
        ratio = sample_index / float(sample_count)
        sampled = _sample_polyline_with_tangent(centerline, centerline_length * ratio)
        if sampled is None:
            continue
        (x, y), (tx, ty) = sampled
        tangent_length = math.hypot(tx, ty)
        if tangent_length <= 1e-9:
            continue
        dlat = float(boundary.start_dlat) + (float(boundary.end_dlat) - float(boundary.start_dlat)) * ratio
        nx = -ty / tangent_length
        ny = tx / tangent_length
        boundary_points.append((x + nx * dlat, y + ny * dlat))
    return boundary_points


def _boundary_span_length(section: SectionPreview, boundary: PreviewFSection) -> float:
    base_length = max(0.0, float(section.length))
    if base_length <= 0.0:
        return 0.0
    if section.center is None or str(section.type_name).lower() != "curve":
        return base_length

    boundary_points = _boundary_polyline(section, boundary)
    if len(boundary_points) >= 3:
        polyline_length = _polyline_length(boundary_points)
        if polyline_length > 0.0:
            return polyline_length

    radius_value = float(section.radius)
    base_radius = abs(radius_value)
    if base_radius <= 1e-9:
        return base_length

    theta = base_length / base_radius
    turn_sign = 1.0 if radius_value >= 0.0 else -1.0
    offset_radius = max(0.0, base_radius + turn_sign * _average_dlat(boundary))
    return max(0.0, abs(theta) * offset_radius)


def generate_wall_mark_file(
    *,
    sections: list[SectionPreview],
    fsects_by_section: list[list[PreviewFSection]],
    mip_name: str,
    uv_rect: MarkUvRect,
    texture_pattern: tuple[MarkTextureSpec, ...] | None = None,
    target_wall_length: float = _DEFAULT_MARK_WALL_LENGTH,
    boundary_match_tolerance: float = _DEFAULT_BOUNDARY_MATCH_TOLERANCE,
    debug_boundary_matching: bool = False,
) -> MarkFile:
    if not sections:
        return MarkFile(entries=())
    if len(sections) != len(fsects_by_section):
        raise ValueError("Section count does not match fsection count")

    track_length = sum(max(0.0, float(section.length)) for section in sections)
    if track_length <= 0.0:
        return MarkFile(entries=())

    textures = texture_pattern
    if textures is None:
        textures = (MarkTextureSpec(mip_name=mip_name, uv_rect=uv_rect),)
    if not textures:
        raise ValueError("At least one texture specification is required")
    if any(not texture.mip_name.strip() for texture in textures):
        raise ValueError("Texture MIP file names cannot be empty")

    boundaries: dict[int, list[tuple[float, float, float, bool]]] = {}
    active_tracks: list[_BoundaryTrack] = []
    next_boundary_id = 0

    section_rows = sorted(
        zip(sections, fsects_by_section),
        key=lambda row: float(row[0].start_dlong),
    )
    for section_index, (section, fsects) in enumerate(section_rows):
        section_start = float(section.start_dlong)
        section_end = section_start + max(0.0, float(section.length))
        if section_end <= section_start:
            continue
        rows = _boundary_rows_for_section(fsects)
        used_track_ids: set[int] = set()
        for row_index, boundary in enumerate(rows):
            signature = _boundary_signature(boundary)
            matches = [
                track
                for track in active_tracks
                if track.boundary_id not in used_track_ids
                and track.surface_type == signature.surface_type
                and track.type2 == signature.type2
                and abs(signature.avg_dlat - track.last_avg_dlat) <= boundary_match_tolerance
            ]
            matched_track = min(
                matches,
                key=lambda track: abs(signature.avg_dlat - track.last_avg_dlat),
                default=None,
            )
            if matched_track is None:
                matched_track = _BoundaryTrack(
                    boundary_id=next_boundary_id,
                    surface_type=signature.surface_type,
                    type2=signature.type2,
                    last_avg_dlat=signature.avg_dlat,
                )
                active_tracks.append(matched_track)
                next_boundary_id += 1

            boundary_id = matched_track.boundary_id
            used_track_ids.add(boundary_id)
            matched_track.last_avg_dlat = signature.avg_dlat

            if debug_boundary_matching:
                _LOGGER.debug(
                    "MRK boundary match section=%s row=%s avg_dlat=%.3f range=(%.3f, %.3f) type=(%s,%s) boundary_id=%s",
                    section_index,
                    row_index,
                    signature.avg_dlat,
                    signature.dlat_range[0],
                    signature.dlat_range[1],
                    signature.surface_type,
                    signature.type2,
                    boundary_id,
                )

            boundaries.setdefault(boundary_id, []).append(
                (
                    section_start,
                    section_end,
                    _boundary_span_length(section, boundary),
                    _average_dlat(boundary) < 0.0,
                )
            )

    def _dlong_at_boundary_distance(
        spans: list[tuple[float, float, float, bool]],
        distance: float,
    ) -> float:
        remaining = max(0.0, float(distance))
        for span_start, span_end, span_length, _ in spans:
            dlong_length = max(0.0, span_end - span_start)
            if dlong_length <= 0.0:
                continue
            effective_span = max(0.0, span_length)
            if effective_span <= 0.0:
                effective_span = dlong_length
            if remaining <= effective_span:
                ratio = remaining / effective_span if effective_span > 1e-9 else 0.0
                return span_start + dlong_length * ratio
            remaining -= effective_span
        return spans[-1][1]

    def _flip_u_for_boundary_distance(
        spans: list[tuple[float, float, float, bool]],
        distance: float,
    ) -> bool:
        remaining = max(0.0, float(distance))
        for _, _, span_length, flip_u in spans:
            effective_span = max(0.0, span_length)
            if effective_span <= 0.0:
                continue
            if remaining <= effective_span:
                return flip_u
            remaining -= effective_span
        return spans[-1][3]

    entries: list[MarkBoundaryEntry] = []
    for boundary_id, raw_spans in sorted(boundaries.items()):
        spans = sorted(raw_spans, key=lambda span: span[0])
        total_boundary_length = sum(max(0.0, span[2]) for span in spans)
        if total_boundary_length <= 0.0:
            total_boundary_length = sum(max(0.0, span[1] - span[0]) for span in spans)
        if total_boundary_length <= 0.0:
            continue

        wall_index = 0
        segment_count = max(1, int(round(total_boundary_length / target_wall_length)))
        if debug_boundary_matching:
            _LOGGER.debug(
                "MRK boundary summary boundary_id=%s span_count=%s total_length=%.3f segment_count=%s",
                boundary_id,
                len(spans),
                total_boundary_length,
                segment_count,
            )
        spacing = total_boundary_length / float(segment_count)
        for index in range(segment_count):
            start_distance = spacing * index
            end_distance = spacing * (index + 1)
            start_dlong = _dlong_at_boundary_distance(spans, start_distance)
            end_dlong = _dlong_at_boundary_distance(spans, end_distance)
            start = dlong_to_section_position(sections, start_dlong, track_length)
            end = dlong_to_section_position(sections, end_dlong, track_length)
            if start is None or end is None:
                continue
            texture = textures[wall_index % len(textures)]
            flip_u = _flip_u_for_boundary_distance(spans, (start_distance + end_distance) * 0.5)
            texture_uv = _flipped_u(texture.uv_rect) if flip_u else texture.uv_rect
            entries.append(
                MarkBoundaryEntry(
                    pointer_name=f"b{boundary_id}_wall{wall_index:04d}",
                    boundary_id=boundary_id,
                    mip_name=texture.mip_name,
                    uv_rect=texture_uv,
                    start=MarkTrackPosition(
                        section=start.section_index,
                        fraction=start.fraction,
                    ),
                    end=MarkTrackPosition(
                        section=end.section_index,
                        fraction=end.fraction,
                    ),
                )
            )
            wall_index += 1

    return MarkFile(entries=tuple(entries))
