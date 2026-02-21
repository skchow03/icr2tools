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


@dataclass(frozen=True)
class _BoundaryDistanceLookup:
    distances: tuple[float, ...]
    ratios: tuple[float, ...]

    @property
    def length(self) -> float:
        if not self.distances:
            return 0.0
        return max(0.0, float(self.distances[-1]))

    def ratio_at_distance(self, distance: float) -> float:
        if not self.distances or not self.ratios:
            return 0.0
        if len(self.distances) == 1:
            return float(self.ratios[0])

        query = min(max(0.0, float(distance)), self.length)
        for index in range(1, len(self.distances)):
            end_distance = float(self.distances[index])
            if query <= end_distance:
                start_distance = float(self.distances[index - 1])
                start_ratio = float(self.ratios[index - 1])
                end_ratio = float(self.ratios[index])
                span = end_distance - start_distance
                if span <= 1e-9:
                    return end_ratio
                blend = (query - start_distance) / span
                return start_ratio + (end_ratio - start_ratio) * blend
        return float(self.ratios[-1])


@dataclass(frozen=True)
class _BoundarySectionSpan:
    section_start: float
    section_end: float
    length: float
    flip_u: bool
    lookup: _BoundaryDistanceLookup


@dataclass(frozen=True)
class _BoundaryRun:
    boundary_id: int
    spans: tuple[_BoundarySectionSpan, ...]


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


def _build_boundary_distance_lookup(section: SectionPreview, boundary: PreviewFSection) -> _BoundaryDistanceLookup:
    boundary_points = _boundary_polyline(section, boundary)
    if len(boundary_points) < 2:
        return _BoundaryDistanceLookup(distances=(0.0, 1.0), ratios=(0.0, 1.0))

    distances: list[float] = [0.0]
    ratios: list[float] = [0.0]
    total = 0.0
    point_count = len(boundary_points)
    for index in range(1, point_count):
        x1, y1 = boundary_points[index - 1]
        x2, y2 = boundary_points[index]
        total += math.hypot(x2 - x1, y2 - y1)
        distances.append(total)
        ratios.append(index / float(point_count - 1))

    if total <= 1e-9:
        return _BoundaryDistanceLookup(distances=(0.0, 1.0), ratios=(0.0, 1.0))
    return _BoundaryDistanceLookup(distances=tuple(distances), ratios=tuple(ratios))


def _boundary_run_dlong_at_distance(run: _BoundaryRun, distance: float) -> float | None:
    if not run.spans:
        return None

    remaining = min(max(0.0, float(distance)), sum(span.length for span in run.spans))
    for span in run.spans:
        if span.length <= 1e-9:
            continue
        if remaining <= span.length:
            ratio = span.lookup.ratio_at_distance(remaining)
            dlong_length = max(0.0, span.section_end - span.section_start)
            return span.section_start + dlong_length * ratio
        remaining -= span.length

    last = run.spans[-1]
    return last.section_end

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

    boundaries: dict[int, list[_BoundarySectionSpan]] = {}

    section_rows = sorted(
        zip(sections, fsects_by_section),
        key=lambda row: float(row[0].start_dlong),
    )
    boundary_rows_by_section = [_boundary_rows_for_section(fsects) for _, fsects in section_rows]
    max_boundary_rows = max((len(rows) for rows in boundary_rows_by_section), default=0)
    if max_boundary_rows <= 0:
        return MarkFile(entries=())

    slot_expected: list[float | None] = [None] * max_boundary_rows
    slot_type: list[tuple[int, int] | None] = [None] * max_boundary_rows

    first_nonempty_rows = next((rows for rows in boundary_rows_by_section if rows), None)
    if first_nonempty_rows is not None:
        for slot, boundary in enumerate(first_nonempty_rows):
            signature = _boundary_signature(boundary)
            slot_expected[slot] = signature.avg_dlat
            slot_type[slot] = (signature.surface_type, signature.type2)

    for section_index, (section, _) in enumerate(section_rows):
        section_start = float(section.start_dlong)
        section_end = section_start + max(0.0, float(section.length))
        if section_end <= section_start:
            continue
        rows = boundary_rows_by_section[section_index]
        used_slots: set[int] = set()
        for row_index, boundary in enumerate(rows):
            signature = _boundary_signature(boundary)
            match_candidates = [
                slot
                for slot in range(max_boundary_rows)
                if slot not in used_slots
                and slot_type[slot] == (signature.surface_type, signature.type2)
                and slot_expected[slot] is not None
                and abs(signature.avg_dlat - float(slot_expected[slot])) <= boundary_match_tolerance
            ]
            matched_slot = min(
                match_candidates,
                key=lambda slot: abs(signature.avg_dlat - float(slot_expected[slot])),
                default=None,
            )

            if matched_slot is None:
                matched_slot = min(row_index, max_boundary_rows - 1)
                existing_type = slot_type[matched_slot]
                if existing_type is not None and existing_type != (signature.surface_type, signature.type2):
                    _LOGGER.debug(
                        "MRK boundary slot fallback type mismatch section=%s row=%s slot=%s expected_type=%s actual_type=%s",
                        section_index,
                        row_index,
                        matched_slot,
                        existing_type,
                        (signature.surface_type, signature.type2),
                    )

            used_slots.add(matched_slot)
            slot_expected[matched_slot] = signature.avg_dlat
            slot_type[matched_slot] = (signature.surface_type, signature.type2)

            if debug_boundary_matching:
                _LOGGER.debug(
                    "MRK boundary match section=%s row=%s avg_dlat=%.3f range=(%.3f, %.3f) type=(%s,%s) slot=%s",
                    section_index,
                    row_index,
                    signature.avg_dlat,
                    signature.dlat_range[0],
                    signature.dlat_range[1],
                    signature.surface_type,
                    signature.type2,
                    matched_slot,
                )

            lookup = _build_boundary_distance_lookup(section, boundary)
            span_length = lookup.length
            if span_length <= 0.0:
                span_length = _boundary_span_length(section, boundary)
            if span_length <= 0.0:
                span_length = max(0.0, section_end - section_start)
            boundaries.setdefault(matched_slot, []).append(
                _BoundarySectionSpan(
                    section_start=section_start,
                    section_end=section_end,
                    length=span_length,
                    flip_u=signature.avg_dlat < 0.0,
                    lookup=lookup,
                )
            )

    boundary_runs: list[_BoundaryRun] = []
    for boundary_id, raw_spans in sorted(boundaries.items()):
        if boundary_id < 0 or boundary_id >= max_boundary_rows:
            _LOGGER.warning(
                "Skipping MRK boundary entry with out-of-range boundary_id=%s max_boundary_rows=%s",
                boundary_id,
                max_boundary_rows,
            )
            continue
        spans = sorted(raw_spans, key=lambda span: span.section_start)
        current: list[_BoundarySectionSpan] = []
        previous_end: float | None = None
        for span in spans:
            if previous_end is not None and span.section_start > previous_end + 1e-6:
                if current:
                    boundary_runs.append(_BoundaryRun(boundary_id=boundary_id, spans=tuple(current)))
                current = []
            current.append(span)
            previous_end = span.section_end
        if current:
            boundary_runs.append(_BoundaryRun(boundary_id=boundary_id, spans=tuple(current)))

    entries: list[MarkBoundaryEntry] = []
    wall_index_by_boundary: dict[int, int] = {}
    for run in boundary_runs:
        total_boundary_length = sum(max(0.0, span.length) for span in run.spans)
        if total_boundary_length <= 0.0:
            continue

        if debug_boundary_matching:
            _LOGGER.debug(
                "MRK boundary summary boundary_id=%s span_count=%s total_length=%.3f",
                run.boundary_id,
                len(run.spans),
                total_boundary_length,
            )

        wall_index = wall_index_by_boundary.get(run.boundary_id, 0)
        position = 0.0
        while position < total_boundary_length - 1e-9:
            start_distance = position
            end_distance = min(position + target_wall_length, total_boundary_length)
            start_dlong = _boundary_run_dlong_at_distance(run, start_distance)
            end_dlong = _boundary_run_dlong_at_distance(run, end_distance)
            if start_dlong is None or end_dlong is None:
                break
            start = dlong_to_section_position(sections, start_dlong, track_length)
            end = dlong_to_section_position(sections, end_dlong, track_length)
            if start is None or end is None:
                position = end_distance
                continue

            texture = textures[wall_index % len(textures)]
            texture_uv = _flipped_u(texture.uv_rect) if run.spans[0].flip_u else texture.uv_rect
            entries.append(
                MarkBoundaryEntry(
                    pointer_name=f"b{run.boundary_id}_wall{wall_index:04d}",
                    boundary_id=run.boundary_id,
                    mip_name=texture.mip_name,
                    uv_rect=texture_uv,
                    start=MarkTrackPosition(section=start.section_index, fraction=start.fraction),
                    end=MarkTrackPosition(section=end.section_index, fraction=end.fraction),
                )
            )
            wall_index += 1
            wall_index_by_boundary[run.boundary_id] = wall_index
            position = end_distance

    return MarkFile(entries=tuple(entries))
