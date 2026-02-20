from __future__ import annotations

import importlib.util
import math
from dataclasses import dataclass
from typing import Callable

from sg_viewer.geometry.topology import is_closed_loop
from sg_viewer.model.preview_fsection import PreviewFSection
from sg_viewer.model.selection import heading_delta
from sg_viewer.model.sg_model import SectionPreview

_NUMPY_SPEC = importlib.util.find_spec("numpy")
if _NUMPY_SPEC is not None:
    import numpy as np
else:
    np = None

Point = tuple[float, float]
FT_TO_WORLD = 500.0
MIN_RADIUS_FT = 50.0
MAX_ARC_DEGREES = 120.0
MIN_CENTERLINE_SEPARATION_FT = 80.0
PERP_SAMPLE_STEP_FT = 10.0


@dataclass(frozen=True)
class IntegrityReport:
    text: str


@dataclass(frozen=True)
class IntegrityProgress:
    current: int
    total: int
    message: str


ProgressCallback = Callable[[IntegrityProgress], None]


def build_integrity_report(
    sections: list[SectionPreview],
    fsects_by_section: list[list[PreviewFSection]],
    on_progress: ProgressCallback | None = None,
) -> IntegrityReport:
    total_steps = _estimate_progress_steps(sections)
    progress = _ProgressTracker(total=total_steps, callback=on_progress)
    progress.update(message="Preparing integrity checks")

    lines: list[str] = []
    lines.append("SG Integrity Report")
    lines.append("=" * 72)

    if not sections:
        lines.append("No sections found.")
        progress.complete(message="Integrity checks complete")
        return IntegrityReport(text="\n".join(lines))

    lines.extend(_topology_report(sections, progress))
    lines.append("")
    lines.extend(_heading_and_boundary_report(sections, fsects_by_section, progress))
    lines.append("")
    lines.extend(_curve_limits_report(sections, progress))
    lines.append("")
    lines.extend(_centerline_clearance_report(sections, fsects_by_section, progress))
    progress.complete(message="Integrity checks complete")

    return IntegrityReport(text="\n".join(lines))


def _topology_report(sections: list[SectionPreview], progress: "_ProgressTracker") -> list[str]:
    n = len(sections)
    closed = is_closed_loop(sections)
    lines = ["Topology", "-" * 72, f"Sections: {n}", f"Closed loop: {'YES' if closed else 'NO'}"]

    unconnected: list[str] = []
    for index, section in enumerate(sections):
        progress.step(message=f"Topology checks: section {index + 1}/{n}")
        invalid_prev = section.previous_id < 0 or section.previous_id >= n
        invalid_next = section.next_id < 0 or section.next_id >= n
        if invalid_prev or invalid_next:
            reasons: list[str] = []
            if invalid_prev:
                reasons.append(f"previous_id={section.previous_id}")
            if invalid_next:
                reasons.append(f"next_id={section.next_id}")
            unconnected.append(f"  - section {index}: {', '.join(reasons)}")

    if unconnected:
        lines.append(f"Unconnected sections: {len(unconnected)}")
        lines.extend(unconnected)
    else:
        lines.append("Unconnected sections: none")

    return lines


def _heading_and_boundary_report(
    sections: list[SectionPreview],
    fsects_by_section: list[list[PreviewFSection]],
    progress: "_ProgressTracker",
) -> list[str]:
    lines = ["Join heading and boundary gap checks", "-" * 72]
    mismatch_lines: list[str] = []
    total = len(sections)

    for index, section in enumerate(sections):
        progress.step(message=f"Join heading checks: section {index + 1}/{total}")
        next_index = index + 1
        if next_index >= total:
            next_index = 0
        next_section = sections[next_index]

        mismatch = heading_delta(section.end_heading, next_section.start_heading)
        if mismatch is None or abs(mismatch) < 0.01:
            continue

        center_gap = _distance(section.end, next_section.start)
        left_gap, right_gap = _boundary_gaps(
            section,
            next_section,
            _safe_get_fsects(fsects_by_section, index),
            _safe_get_fsects(fsects_by_section, next_index),
        )
        mismatch_lines.append(
            (
                f"  - {index} -> {next_index}: heading Δ={mismatch:.3f}°, "
                f"centerline gap={center_gap / FT_TO_WORLD:.2f} ft, "
                f"left boundary gap={left_gap / FT_TO_WORLD:.2f} ft, "
                f"right boundary gap={right_gap / FT_TO_WORLD:.2f} ft"
            )
        )

    if mismatch_lines:
        lines.append(f"Heading mismatches: {len(mismatch_lines)}")
        lines.extend(mismatch_lines)
    else:
        lines.append("Heading mismatches: none")

    return lines


def _curve_limits_report(sections: list[SectionPreview], progress: "_ProgressTracker") -> list[str]:
    lines = ["Curve limits", "-" * 72]
    long_arc: list[str] = []
    tight_radius: list[str] = []
    min_radius_world = MIN_RADIUS_FT * FT_TO_WORLD

    for index, section in enumerate(sections):
        progress.step(message=f"Curve limit checks: section {index + 1}/{len(sections)}")
        if section.type_name != "curve" or not section.radius:
            continue

        radius_abs = abs(float(section.radius))
        if radius_abs > 0:
            arc_degrees = math.degrees(float(section.length) / radius_abs)
            if arc_degrees > MAX_ARC_DEGREES:
                long_arc.append(f"  - section {index}: arc={arc_degrees:.2f}°")

        if radius_abs < min_radius_world:
            tight_radius.append(
                f"  - section {index}: radius={radius_abs / FT_TO_WORLD:.2f} ft"
            )

    if long_arc:
        lines.append(f"Curves with arc > {MAX_ARC_DEGREES:.0f}°: {len(long_arc)}")
        lines.extend(long_arc)
    else:
        lines.append(f"Curves with arc > {MAX_ARC_DEGREES:.0f}°: none")

    if tight_radius:
        lines.append(f"Curves with radius < {MIN_RADIUS_FT:.0f} ft: {len(tight_radius)}")
        lines.extend(tight_radius)
    else:
        lines.append(f"Curves with radius < {MIN_RADIUS_FT:.0f} ft: none")

    return lines


def _centerline_clearance_report(
    sections: list[SectionPreview],
    fsects_by_section: list[list[PreviewFSection]],
    progress: "_ProgressTracker",
) -> list[str]:
    lines = ["Centerline clearance and boundary ownership", "-" * 72]
    sample_step_world = PERP_SAMPLE_STEP_FT * FT_TO_WORLD
    probe_half_len_world = MIN_CENTERLINE_SEPARATION_FT * FT_TO_WORLD

    all_segments: list[tuple[int, Point, Point]] = []
    for section_index, section in enumerate(sections):
        progress.step(
            message=f"Centerline setup: section {section_index + 1}/{len(sections)}"
        )
        for seg_start, seg_end in _polyline_segments(section.polyline):
            all_segments.append((section_index, seg_start, seg_end))

    segment_index = _build_segment_spatial_index(
        all_segments,
        search_radius=probe_half_len_world,
    )

    sample_counts = _centerline_sample_counts(sections, sample_step_world)
    total_samples = sum(sample_counts)
    processed_samples = 0
    findings: list[str] = []
    for section_index, section in enumerate(sections):
        section_level_fallback_hit = _find_close_centerline(
            source_section_index=section_index,
            source_polyline=section.polyline,
            max_distance=probe_half_len_world,
            sections=sections,
        )
        for sample_point, tangent in _sample_polyline(section.polyline, sample_step_world):
            processed_samples += 1
            if total_samples > 0:
                progress.step(
                    message=(
                        "Centerline spacing checks: "
                        f"section {section_index + 1}/{len(sections)} sample "
                        f"{processed_samples}/{total_samples}"
                    )
                )
            normal = _left_normal(tangent)
            if normal is None:
                continue

            hit = _find_probe_proximity(
                section_index,
                sample_point,
                normal,
                probe_half_len_world,
                all_segments,
                segment_index,
                sections,
            )
            if hit is None:
                hit = section_level_fallback_hit
            if hit is None:
                continue
            findings.append(
                (
                    f"  - section {section_index} near ({sample_point[0] / FT_TO_WORLD:.1f}, "
                    f"{sample_point[1] / FT_TO_WORLD:.1f}) ft intersects section {hit} "
                    f"within ±{MIN_CENTERLINE_SEPARATION_FT:.0f} ft"
                )
            )
            break

    if findings:
        lines.append(f"Sections with < {MIN_CENTERLINE_SEPARATION_FT:.0f} ft perpendicular spacing: {len(findings)}")
        lines.extend(findings)
    else:
        lines.append(
            (
                "No section had a perpendicular "
                f"±{MIN_CENTERLINE_SEPARATION_FT:.0f} ft probe intersect another centerline."
            )
        )

    lines.extend(
        _boundary_centerline_ownership_report(
            sections, fsects_by_section, sample_step_world, progress
        )
    )

    lines.append(
        f"Sampling step: {PERP_SAMPLE_STEP_FT:.0f} ft along each centerline section."
    )
    return lines


def _boundary_centerline_ownership_report(
    sections: list[SectionPreview],
    fsects_by_section: list[list[PreviewFSection]],
    sample_step_world: float,
    progress: "_ProgressTracker",
) -> list[str]:
    lines: list[str] = []
    findings: list[str] = []
    spatial_index: _SectionSegmentSpatialIndex | None = None
    prepared_polyline_cache: dict[int, _PreparedPolyline] | None = None
    if np is not None:
        prepared_polyline_cache = _build_prepared_polyline_cache(sections)
    spatial_index = _build_section_segment_spatial_index(sections, sample_step_world)

    for section_index, section in enumerate(sections):
        progress.step(
            message=f"Boundary ownership checks: section {section_index + 1}/{len(sections)}"
        )
        samples = _sample_polyline_with_distance(section.polyline, sample_step_world)
        if not samples:
            continue

        section_fsects = _safe_get_fsects(fsects_by_section, section_index)
        for sample_point, tangent, along_distance, total_distance in samples:
            normal = _left_normal(tangent)
            if normal is None:
                continue

            ratio = 0.0 if total_distance <= 0 else min(max(along_distance / total_distance, 0.0), 1.0)
            left_dlat, right_dlat = _boundary_offsets_at_ratio(section_fsects, ratio)
            for side, dlat in (("left", left_dlat), ("right", right_dlat)):
                boundary_point = (
                    sample_point[0] + normal[0] * dlat,
                    sample_point[1] + normal[1] * dlat,
                )
                own_prepared_polyline = None
                if prepared_polyline_cache is not None:
                    own_prepared_polyline = prepared_polyline_cache.get(section_index)
                own_dist = _point_to_polyline_distance(
                    boundary_point,
                    section.polyline,
                    own_prepared_polyline,
                )
                rival_index, rival_dist = _nearest_section_distance(
                    boundary_point,
                    sections,
                    exclude_index=section_index,
                    prepared_polyline_cache=prepared_polyline_cache,
                    spatial_index=spatial_index,
                )
                if rival_index is None or rival_dist is None:
                    continue
                if _is_adjacent_section(section_index, rival_index, sections):
                    continue
                if rival_dist + 1e-6 >= own_dist:
                    continue

                findings.append(
                    (
                        f"  - section {section_index} {side} boundary near "
                        f"({boundary_point[0] / FT_TO_WORLD:.1f}, {boundary_point[1] / FT_TO_WORLD:.1f}) ft "
                        f"is closer to section {rival_index} centerline "
                        f"({rival_dist / FT_TO_WORLD:.2f} ft) than its own "
                        f"({own_dist / FT_TO_WORLD:.2f} ft)"
                    )
                )
                break

            if findings and findings[-1].startswith(f"  - section {section_index} "):
                break

    if findings:
        lines.append(
            f"Boundary points closer to a different centerline: {len(findings)}"
        )
        lines.extend(findings)
    else:
        lines.append("Boundary points closer to a different centerline: none")

    return lines


def _estimate_progress_steps(sections: list[SectionPreview]) -> int:
    if not sections:
        return 1

    sample_step_world = PERP_SAMPLE_STEP_FT * FT_TO_WORLD
    centerline_samples = sum(_count_polyline_samples(section.polyline, sample_step_world) for section in sections)
    return 1 + (4 * len(sections)) + centerline_samples


def _centerline_sample_counts(sections: list[SectionPreview], step: float) -> list[int]:
    return [_count_polyline_samples(section.polyline, step) for section in sections]


def _count_polyline_samples(polyline: list[Point], step: float) -> int:
    if len(polyline) < 2:
        return 0
    total_distance = 0.0
    for idx in range(len(polyline) - 1):
        total_distance += _distance(polyline[idx], polyline[idx + 1])
    if total_distance <= 0:
        return 0
    return max(1, int(math.floor(total_distance / max(step, 1.0))) + 1)


@dataclass
class _ProgressTracker:
    total: int
    callback: ProgressCallback | None
    current: int = 0

    def update(self, message: str) -> None:
        if self.callback is None:
            return
        total = max(self.total, 1)
        current = min(max(self.current, 0), total)
        self.callback(IntegrityProgress(current=current, total=total, message=message))

    def step(self, count: int = 1, message: str = "") -> None:
        self.current += max(count, 0)
        self.update(message=message)

    def complete(self, message: str) -> None:
        self.current = max(self.total, self.current)
        self.update(message=message)


def _boundary_offsets_at_ratio(
    fsects: list[PreviewFSection], ratio: float
) -> tuple[float, float]:
    dlats = [0.0]
    for fsect in fsects:
        dlat = float(fsect.start_dlat) + (float(fsect.end_dlat) - float(fsect.start_dlat)) * ratio
        dlats.append(dlat)
    return max(dlats), min(dlats)


def _safe_get_fsects(
    fsects_by_section: list[list[PreviewFSection]], index: int
) -> list[PreviewFSection]:
    if index < 0 or index >= len(fsects_by_section):
        return []
    return list(fsects_by_section[index])


def _boundary_gaps(
    section: SectionPreview,
    next_section: SectionPreview,
    section_fsects: list[PreviewFSection],
    next_fsects: list[PreviewFSection],
) -> tuple[float, float]:
    sec_heading = _normalize(section.end_heading)
    next_heading = _normalize(next_section.start_heading)
    if sec_heading is None:
        sec_heading = _heading_from_segment(section.start, section.end)
    if next_heading is None:
        next_heading = _heading_from_segment(next_section.start, next_section.end)

    if sec_heading is None or next_heading is None:
        center_gap = _distance(section.end, next_section.start)
        return center_gap, center_gap

    section_left, section_right = _boundary_points(section.end, sec_heading, section_fsects, endtype="end")
    next_left, next_right = _boundary_points(next_section.start, next_heading, next_fsects, endtype="start")

    return _distance(section_left, next_left), _distance(section_right, next_right)


def _boundary_points(
    point: Point,
    heading: tuple[float, float],
    fsects: list[PreviewFSection],
    *,
    endtype: str,
) -> tuple[Point, Point]:
    dlats = [0.0]
    for fsect in fsects:
        dlat = fsect.end_dlat if endtype == "end" else fsect.start_dlat
        dlats.append(float(dlat))

    left_dlat = max(dlats)
    right_dlat = min(dlats)
    nx, ny = -heading[1], heading[0]

    left = (point[0] + nx * left_dlat, point[1] + ny * left_dlat)
    right = (point[0] + nx * right_dlat, point[1] + ny * right_dlat)
    return left, right


def _polyline_segments(polyline: list[Point]) -> list[tuple[Point, Point]]:
    segments: list[tuple[Point, Point]] = []
    for idx in range(len(polyline) - 1):
        segments.append((polyline[idx], polyline[idx + 1]))
    return segments


def _sample_polyline(polyline: list[Point], step: float) -> list[tuple[Point, tuple[float, float]]]:
    if len(polyline) < 2:
        return []

    distances = [0.0]
    total = 0.0
    for idx in range(len(polyline) - 1):
        seg_len = _distance(polyline[idx], polyline[idx + 1])
        total += seg_len
        distances.append(total)

    if total <= 0:
        return []

    samples: list[tuple[Point, tuple[float, float]]] = []
    d = 0.0
    while d <= total:
        samples.append(_interpolate_at_distance(polyline, distances, d))
        d += max(step, 1.0)

    if samples:
        samples[-1] = _interpolate_at_distance(polyline, distances, total)

    return samples


def _interpolate_at_distance(
    polyline: list[Point], cumulative: list[float], target_d: float
) -> tuple[Point, tuple[float, float]]:
    for idx in range(len(cumulative) - 1):
        start_d = cumulative[idx]
        end_d = cumulative[idx + 1]
        if target_d > end_d and idx < len(cumulative) - 2:
            continue

        p0 = polyline[idx]
        p1 = polyline[idx + 1]
        seg_len = max(end_d - start_d, 1e-9)
        ratio = (target_d - start_d) / seg_len
        ratio = min(max(ratio, 0.0), 1.0)
        point = (p0[0] + (p1[0] - p0[0]) * ratio, p0[1] + (p1[1] - p0[1]) * ratio)
        tangent = _normalize((p1[0] - p0[0], p1[1] - p0[1]))
        if tangent is None:
            tangent = (1.0, 0.0)
        return point, tangent

    p0 = polyline[-2]
    p1 = polyline[-1]
    tangent = _normalize((p1[0] - p0[0], p1[1] - p0[1])) or (1.0, 0.0)
    return polyline[-1], tangent


def _sample_polyline_with_distance(
    polyline: list[Point], step: float
) -> list[tuple[Point, tuple[float, float], float, float]]:
    if len(polyline) < 2:
        return []

    distances = [0.0]
    total = 0.0
    for idx in range(len(polyline) - 1):
        seg_len = _distance(polyline[idx], polyline[idx + 1])
        total += seg_len
        distances.append(total)

    if total <= 0:
        return []

    samples: list[tuple[Point, tuple[float, float], float, float]] = []
    d = 0.0
    while d <= total:
        point, tangent = _interpolate_at_distance(polyline, distances, d)
        samples.append((point, tangent, d, total))
        d += max(step, 1.0)

    if samples:
        point, tangent = _interpolate_at_distance(polyline, distances, total)
        samples[-1] = (point, tangent, total, total)

    return samples


def _nearest_section_distance(
    point: Point,
    sections: list[SectionPreview],
    *,
    exclude_index: int,
    prepared_polyline_cache: dict[int, "_PreparedPolyline"] | None = None,
    spatial_index: "_SectionSegmentSpatialIndex | None" = None,
) -> tuple[int | None, float | None]:
    nearest_index: int | None = None
    nearest_distance: float | None = None

    if spatial_index is not None:
        section_best_distance: dict[int, float] = {}
        max_radius = 8
        for radius_cells in range(1, max_radius + 1):
            candidate_segment_indices = spatial_index.candidate_segments(point, radius_cells)
            if not candidate_segment_indices:
                continue

            for segment_index in candidate_segment_indices:
                indexed_segment = spatial_index.segments[segment_index]
                section_index = indexed_segment.section_index
                if section_index == exclude_index:
                    continue
                distance = _point_to_segment_distance(
                    point,
                    indexed_segment.seg_start,
                    indexed_segment.seg_end,
                )
                best_so_far = section_best_distance.get(section_index)
                if best_so_far is None or distance < best_so_far:
                    section_best_distance[section_index] = distance

            if section_best_distance:
                break

        if section_best_distance:
            nearest_index = min(section_best_distance, key=section_best_distance.get)
            nearest_distance = section_best_distance[nearest_index]
            return nearest_index, nearest_distance

    for index, section in enumerate(sections):
        if index == exclude_index:
            continue
        prepared_polyline = None
        if prepared_polyline_cache is not None:
            prepared_polyline = prepared_polyline_cache.get(index)
        distance = _point_to_polyline_distance(point, section.polyline, prepared_polyline)
        if nearest_distance is None or distance < nearest_distance:
            nearest_distance = distance
            nearest_index = index

    return nearest_index, nearest_distance


@dataclass(frozen=True)
class _IndexedSectionSegment:
    section_index: int
    seg_start: Point
    seg_end: Point
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class _SectionSegmentSpatialIndex:
    bin_size: float
    bins: dict[tuple[int, int], list[int]]
    segments: list[_IndexedSectionSegment]

    def candidate_segments(self, point: Point, radius_cells: int) -> list[int]:
        ix, iy = _grid_key(point, self.bin_size)
        min_ix = ix - radius_cells
        max_ix = ix + radius_cells
        min_iy = iy - radius_cells
        max_iy = iy + radius_cells

        candidates: set[int] = set()
        for bx in range(min_ix, max_ix + 1):
            for by in range(min_iy, max_iy + 1):
                candidates.update(self.bins.get((bx, by), []))
        return list(candidates)


def _build_section_segment_spatial_index(
    sections: list[SectionPreview],
    step: float,
) -> _SectionSegmentSpatialIndex | None:
    indexed_segments: list[_IndexedSectionSegment] = []
    for section_index, section in enumerate(sections):
        for seg_start, seg_end in _polyline_segments(section.polyline):
            min_x = min(seg_start[0], seg_end[0])
            max_x = max(seg_start[0], seg_end[0])
            min_y = min(seg_start[1], seg_end[1])
            max_y = max(seg_start[1], seg_end[1])
            indexed_segments.append(
                _IndexedSectionSegment(
                    section_index=section_index,
                    seg_start=seg_start,
                    seg_end=seg_end,
                    bbox=(min_x, min_y, max_x, max_y),
                )
            )

    if not indexed_segments:
        return None

    bin_size = max(step * 4.0, FT_TO_WORLD)
    bins: dict[tuple[int, int], list[int]] = {}
    for segment_index, indexed_segment in enumerate(indexed_segments):
        min_x, min_y, max_x, max_y = indexed_segment.bbox
        min_ix, min_iy = _grid_key((min_x, min_y), bin_size)
        max_ix, max_iy = _grid_key((max_x, max_y), bin_size)

        for ix in range(min_ix, max_ix + 1):
            for iy in range(min_iy, max_iy + 1):
                bins.setdefault((ix, iy), []).append(segment_index)

    return _SectionSegmentSpatialIndex(
        bin_size=bin_size,
        bins=bins,
        segments=indexed_segments,
    )


def _grid_key(point: Point, bin_size: float) -> tuple[int, int]:
    return (int(math.floor(point[0] / bin_size)), int(math.floor(point[1] / bin_size)))


@dataclass(frozen=True)
class _PreparedPolyline:
    points: np.ndarray
    start: np.ndarray
    seg: np.ndarray
    seg_len_sq_safe: np.ndarray


def _build_prepared_polyline_cache(
    sections: list[SectionPreview],
) -> dict[int, _PreparedPolyline]:
    if np is None:
        return {}

    prepared: dict[int, _PreparedPolyline] = {}
    for index, section in enumerate(sections):
        if len(section.polyline) < 2:
            continue
        points = np.asarray(section.polyline, dtype=float)
        start = points[:-1]
        seg = points[1:] - start
        seg_len_sq = np.einsum("ij,ij->i", seg, seg)
        seg_len_sq_safe = np.where(seg_len_sq > 1e-12, seg_len_sq, 1.0)
        prepared[index] = _PreparedPolyline(
            points=points,
            start=start,
            seg=seg,
            seg_len_sq_safe=seg_len_sq_safe,
        )

    return prepared


def _point_to_polyline_distance(
    point: Point,
    polyline: list[Point],
    prepared_polyline: "_PreparedPolyline | None" = None,
) -> float:
    if not polyline:
        return math.inf
    if len(polyline) == 1:
        return _distance(point, polyline[0])

    if np is not None:
        prepared = prepared_polyline
        if prepared is None:
            points = np.asarray(polyline, dtype=float)
            start = points[:-1]
            seg = points[1:] - start
            seg_len_sq = np.einsum("ij,ij->i", seg, seg)
            seg_len_sq_safe = np.where(seg_len_sq > 1e-12, seg_len_sq, 1.0)
            prepared = _PreparedPolyline(
                points=points,
                start=start,
                seg=seg,
                seg_len_sq_safe=seg_len_sq_safe,
            )
        return _point_to_polyline_distance_numpy(point, prepared)

    return min(
        _point_to_segment_distance(point, polyline[idx], polyline[idx + 1])
        for idx in range(len(polyline) - 1)
    )


def _point_to_polyline_distance_numpy(point: Point, prepared_polyline: _PreparedPolyline) -> float:
    if prepared_polyline.points.shape[0] < 2:
        return math.inf

    point_array = np.asarray(point, dtype=float)
    to_point = point_array - prepared_polyline.start

    t = np.einsum("ij,ij->i", to_point, prepared_polyline.seg) / prepared_polyline.seg_len_sq_safe
    t = np.clip(t, 0.0, 1.0)

    closest = prepared_polyline.start + prepared_polyline.seg * t[:, None]
    delta = closest - point_array
    dists = np.hypot(delta[:, 0], delta[:, 1])

    if dists.size == 0:
        return math.inf
    return float(np.min(dists))


def _point_to_segment_distance(point: Point, start: Point, end: Point) -> float:
    closest = _closest_point_on_segment(point, start, end)
    return _distance(point, closest)


def _find_probe_proximity(
    source_section_index: int,
    sample_point: Point,
    sample_normal: tuple[float, float],
    max_perpendicular_distance: float,
    all_segments: list[tuple[int, Point, Point]],
    segment_index: "_SegmentSpatialIndex | None",
    sections: list[SectionPreview],
) -> int | None:
    candidates = range(len(all_segments))
    if segment_index is not None:
        candidates = segment_index.query(sample_point, max_perpendicular_distance)

    for segment_idx in candidates:
        section_index, seg_start, seg_end = all_segments[segment_idx]
        if section_index == source_section_index:
            continue
        if _is_adjacent_section(source_section_index, section_index, sections):
            continue

        closest = _closest_point_on_segment(sample_point, seg_start, seg_end)
        radial_distance = _distance(sample_point, closest)
        if radial_distance > max_perpendicular_distance:
            continue

        to_closest = (closest[0] - sample_point[0], closest[1] - sample_point[1])
        perpendicular_distance = abs(
            to_closest[0] * sample_normal[0] + to_closest[1] * sample_normal[1]
        )
        if perpendicular_distance <= max_perpendicular_distance:
            return section_index
    return None


@dataclass(frozen=True)
class _SegmentSpatialIndex:
    bin_size: float
    bins: dict[tuple[int, int], list[int]]
    bboxes: list[tuple[float, float, float, float]]

    def query(self, point: Point, radius: float) -> list[int]:
        min_x = point[0] - radius
        max_x = point[0] + radius
        min_y = point[1] - radius
        max_y = point[1] + radius

        min_ix, min_iy = _grid_key((min_x, min_y), self.bin_size)
        max_ix, max_iy = _grid_key((max_x, max_y), self.bin_size)

        candidate_indices: set[int] = set()
        for ix in range(min_ix, max_ix + 1):
            for iy in range(min_iy, max_iy + 1):
                candidate_indices.update(self.bins.get((ix, iy), []))

        overlapping: list[int] = []
        for segment_index in candidate_indices:
            seg_min_x, seg_min_y, seg_max_x, seg_max_y = self.bboxes[segment_index]
            if seg_max_x < min_x or seg_min_x > max_x:
                continue
            if seg_max_y < min_y or seg_min_y > max_y:
                continue
            overlapping.append(segment_index)

        return overlapping


def _build_segment_spatial_index(
    all_segments: list[tuple[int, Point, Point]],
    search_radius: float,
) -> _SegmentSpatialIndex | None:
    if not all_segments:
        return None

    bin_size = max(search_radius, FT_TO_WORLD)
    bins: dict[tuple[int, int], list[int]] = {}
    bboxes: list[tuple[float, float, float, float]] = []

    for segment_index, (_, start, end) in enumerate(all_segments):
        min_x = min(start[0], end[0])
        max_x = max(start[0], end[0])
        min_y = min(start[1], end[1])
        max_y = max(start[1], end[1])
        bboxes.append((min_x, min_y, max_x, max_y))

        min_ix, min_iy = _grid_key((min_x, min_y), bin_size)
        max_ix, max_iy = _grid_key((max_x, max_y), bin_size)
        for ix in range(min_ix, max_ix + 1):
            for iy in range(min_iy, max_iy + 1):
                bins.setdefault((ix, iy), []).append(segment_index)

    return _SegmentSpatialIndex(bin_size=bin_size, bins=bins, bboxes=bboxes)


def _find_close_centerline(
    source_section_index: int,
    source_polyline: list[Point],
    max_distance: float,
    sections: list[SectionPreview],
) -> int | None:
    source_segments = _polyline_segments(source_polyline)
    for target_index, target in enumerate(sections):
        if target_index == source_section_index:
            continue
        if _is_adjacent_section(source_section_index, target_index, sections):
            continue

        target_segments = _polyline_segments(target.polyline)
        for source_start, source_end in source_segments:
            for target_start, target_end in target_segments:
                if (
                    _segment_to_segment_distance(
                        source_start,
                        source_end,
                        target_start,
                        target_end,
                    )
                    <= max_distance
                ):
                    return target_index
    return None


def _closest_point_on_segment(point: Point, start: Point, end: Point) -> Point:
    seg_x = end[0] - start[0]
    seg_y = end[1] - start[1]
    seg_len_sq = seg_x * seg_x + seg_y * seg_y
    if seg_len_sq <= 1e-12:
        return start

    proj = ((point[0] - start[0]) * seg_x + (point[1] - start[1]) * seg_y) / seg_len_sq
    proj = min(max(proj, 0.0), 1.0)
    return (start[0] + proj * seg_x, start[1] + proj * seg_y)


def _segment_to_segment_distance(a0: Point, a1: Point, b0: Point, b1: Point) -> float:
    if _segments_intersect(a0, a1, b0, b1):
        return 0.0

    return min(
        _point_to_segment_distance(a0, b0, b1),
        _point_to_segment_distance(a1, b0, b1),
        _point_to_segment_distance(b0, a0, a1),
        _point_to_segment_distance(b1, a0, a1),
    )


def _segments_intersect(a0: Point, a1: Point, b0: Point, b1: Point) -> bool:
    def orientation(p: Point, q: Point, r: Point) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    def on_segment(p: Point, q: Point, r: Point) -> bool:
        return (
            min(p[0], r[0]) - 1e-9 <= q[0] <= max(p[0], r[0]) + 1e-9
            and min(p[1], r[1]) - 1e-9 <= q[1] <= max(p[1], r[1]) + 1e-9
        )

    o1 = orientation(a0, a1, b0)
    o2 = orientation(a0, a1, b1)
    o3 = orientation(b0, b1, a0)
    o4 = orientation(b0, b1, a1)

    if (o1 > 0) != (o2 > 0) and (o3 > 0) != (o4 > 0):
        return True

    if abs(o1) <= 1e-9 and on_segment(a0, b0, a1):
        return True
    if abs(o2) <= 1e-9 and on_segment(a0, b1, a1):
        return True
    if abs(o3) <= 1e-9 and on_segment(b0, a0, b1):
        return True
    if abs(o4) <= 1e-9 and on_segment(b0, a1, b1):
        return True

    return False


def _is_adjacent_section(
    source_index: int,
    target_index: int,
    sections: list[SectionPreview],
) -> bool:
    if source_index < 0 or source_index >= len(sections):
        return False
    if target_index < 0 or target_index >= len(sections):
        return False

    source = sections[source_index]
    target = sections[target_index]
    return target_index in (source.previous_id, source.next_id) or source_index in (
        target.previous_id,
        target.next_id,
    )



def _left_normal(tangent: tuple[float, float]) -> tuple[float, float] | None:
    normalized = _normalize(tangent)
    if normalized is None:
        return None
    return (-normalized[1], normalized[0])


def _heading_from_segment(start: Point, end: Point) -> tuple[float, float] | None:
    return _normalize((end[0] - start[0], end[1] - start[1]))


def _normalize(vec: tuple[float, float] | None) -> tuple[float, float] | None:
    if vec is None:
        return None
    length = math.hypot(vec[0], vec[1])
    if length <= 1e-9:
        return None
    return (vec[0] / length, vec[1] / length)


def _distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])
