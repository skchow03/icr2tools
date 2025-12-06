from __future__ import annotations

from dataclasses import dataclass, replace
import math
from pathlib import Path
from typing import Iterable, List, Tuple

from icr2_core.trk.sg_classes import SGFile
from icr2_core.trk.trk_classes import TRKFile
from icr2_core.trk.trk_utils import getxyz
from track_viewer.geometry import CenterlineIndex, build_centerline_index, sample_centerline

Point = Tuple[float, float]
Transform = tuple[float, tuple[float, float]]


@dataclass(frozen=True)
class SectionPreview:
    section_id: int
    type_name: str
    previous_id: int
    next_id: int
    start: Point
    end: Point
    start_dlong: float
    length: float
    center: Point | None
    sang1: float | None
    sang2: float | None
    eang1: float | None
    eang2: float | None
    radius: float | None
    start_heading: tuple[float, float] | None
    end_heading: tuple[float, float] | None
    polyline: list[Point]


@dataclass(frozen=True)
class PreviewData:
    sgfile: SGFile
    trk: TRKFile
    cline: List[Point]
    sampled_centerline: List[Point]
    sampled_dlongs: List[float]
    sampled_bounds: tuple[float, float, float, float]
    centerline_index: CenterlineIndex
    track_length: float
    start_finish_mapping: tuple[Point, Point, Point] | None
    sections: list[SectionPreview]
    section_endpoints: list[tuple[Point, Point]]
    status_message: str


def load_preview(path: Path) -> PreviewData:
    sgfile = SGFile.from_sg(str(path))
    trk = TRKFile.from_sg(str(path))
    cline = get_cline_pos(trk)
    sampled, sampled_dlongs, bounds = sample_centerline(trk, cline)

    if not sampled or bounds is None:
        raise ValueError("Failed to build centreline from SG file")

    centerline_index = build_centerline_index(sampled, bounds)
    track_length = float(trk.trklength)
    start_finish_mapping = _centerline_point_normal_and_tangent(trk, cline, track_length, 0.0)
    sections = _build_sections(sgfile, trk, cline, track_length)
    section_endpoints = [(sect.start, sect.end) for sect in sections]

    return PreviewData(
        sgfile=sgfile,
        trk=trk,
        cline=cline,
        sampled_centerline=sampled,
        sampled_dlongs=sampled_dlongs,
        sampled_bounds=bounds,
        centerline_index=centerline_index,
        track_length=track_length,
        start_finish_mapping=start_finish_mapping,
        sections=sections,
        section_endpoints=section_endpoints,
        status_message=f"Loaded {path.name}",
    )


def _build_sections(
    sgfile: SGFile, trk: TRKFile, cline: Iterable[Point] | None, track_length: float
) -> list[SectionPreview]:
    sections: list[SectionPreview] = []

    if cline is None or track_length <= 0:
        return sections

    for idx, (sg_sect, trk_sect) in enumerate(zip(sgfile.sects, trk.sects)):
        start_dlong = float(trk_sect.start_dlong) % track_length
        length = float(trk_sect.length)

        start = (float(sg_sect.start_x), float(sg_sect.start_y))
        end = (
            float(getattr(sg_sect, "end_x", start[0])),
            float(getattr(sg_sect, "end_y", start[1])),
        )

        center = None
        radius = None
        sang1 = sang2 = eang1 = eang2 = None
        if getattr(sg_sect, "type", None) == 2:
            center = (float(sg_sect.center_x), float(sg_sect.center_y))
            radius = float(sg_sect.radius)
            sang1 = float(sg_sect.sang1)
            sang2 = float(sg_sect.sang2)
            eang1 = float(sg_sect.eang1)
            eang2 = float(sg_sect.eang2)

        polyline = _build_section_polyline(
            "curve" if getattr(sg_sect, "type", None) == 2 else "straight",
            start,
            end,
            center,
            radius,
            (sang1, sang2) if sang1 is not None and sang2 is not None else None,
            (eang1, eang2) if eang1 is not None and eang2 is not None else None,
        )

        start_heading, end_heading = _derive_heading_vectors(polyline, sang1, sang2, eang1, eang2)

        sections.append(
            SectionPreview(
                section_id=idx,
                type_name="curve" if getattr(sg_sect, "type", None) == 2 else "straight",
                previous_id=int(getattr(sg_sect, "sec_prev", idx - 1)),
                next_id=int(getattr(sg_sect, "sec_next", idx + 1)),
                start=start,
                end=end,
                start_dlong=start_dlong,
                length=length,
                center=center,
                sang1=sang1,
                sang2=sang2,
                eang1=eang1,
                eang2=eang2,
                radius=radius,
                start_heading=start_heading,
                end_heading=end_heading,
                polyline=polyline,
            )
        )

    return sections


def _centerline_point_normal_and_tangent(
    trk: TRKFile, cline: Iterable[Point] | None, track_length: float, dlong: float
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]] | None:
    if cline is None or track_length <= 0:
        return None

    def _wrap(value: float) -> float:
        while value < 0:
            value += track_length
        while value >= track_length:
            value -= track_length
        return value

    base = _wrap(float(dlong))
    delta = max(50.0, track_length * 0.002)
    prev_dlong = _wrap(base - delta)
    next_dlong = _wrap(base + delta)

    px, py, _ = getxyz(trk, prev_dlong, 0, cline)
    nx, ny, _ = getxyz(trk, next_dlong, 0, cline)
    cx, cy, _ = getxyz(trk, base, 0, cline)

    vx = nx - px
    vy = ny - py
    length = (vx * vx + vy * vy) ** 0.5
    if length == 0:
        return None

    tangent = (vx / length, vy / length)
    normal = (-vy / length, vx / length)

    return (cx, cy), normal, tangent


def _build_section_polyline(
    type_name: str,
    start: Point,
    end: Point,
    center: Point | None,
    radius: float | None,
    start_heading: tuple[float, float] | None,
    end_heading: tuple[float, float] | None,
) -> list[Point]:
    if type_name != "curve" or center is None:
        return [start, end]

    def _choose_ccw_direction(start_vec: tuple[float, float], end_vec: tuple[float, float]) -> bool:
        start_norm = _normalize_heading(start_vec)
        end_norm = _normalize_heading(end_vec)
        if start_norm and end_norm:
            cross = start_norm[0] * end_norm[1] - start_norm[1] * end_norm[0]
            if abs(cross) > 1e-9:
                return cross > 0
        return True

    def _heading_prefers_ccw(vec: tuple[float, float], heading: tuple[float, float]) -> bool | None:
        heading_norm = _normalize_heading(heading)
        vec_norm = _normalize_heading(vec)
        if heading_norm is None or vec_norm is None:
            return None
        ccw_tangent = (-vec_norm[1], vec_norm[0])
        cw_tangent = (vec_norm[1], -vec_norm[0])
        ccw_dot = ccw_tangent[0] * heading_norm[0] + ccw_tangent[1] * heading_norm[1]
        cw_dot = cw_tangent[0] * heading_norm[0] + cw_tangent[1] * heading_norm[1]
        if abs(ccw_dot - cw_dot) < 1e-9:
            return None
        return ccw_dot > cw_dot

    def _heading_radius_angle(
        heading: tuple[float, float] | None, reference_vec: tuple[float, float] | None
    ) -> float | None:
        heading_norm = _normalize_heading(heading)
        if heading_norm is None:
            return None

        heading_angle = math.atan2(heading_norm[1], heading_norm[0])
        candidates = [heading_angle - math.pi / 2, heading_angle + math.pi / 2]

        ref_norm = _normalize_heading(reference_vec)
        if ref_norm is None:
            return candidates[0]

        def _dot(angle: float) -> float:
            return math.cos(angle) * ref_norm[0] + math.sin(angle) * ref_norm[1]

        best_angle = max(candidates, key=_dot)
        return best_angle

    cx, cy = center
    start_vec = (start[0] - cx, start[1] - cy)
    end_vec = (end[0] - cx, end[1] - cy)
    radius_length = radius if radius is not None and radius > 0 else (start_vec[0] ** 2 + start_vec[1] ** 2) ** 0.5

    if radius_length <= 0:
        return [start, end]

    start_angle = _heading_radius_angle(start_heading, start_vec)
    if start_angle is None:
        start_angle = math.atan2(start_vec[1], start_vec[0])

    end_angle = _heading_radius_angle(end_heading, end_vec)
    if end_angle is None:
        end_angle = math.atan2(end_vec[1], end_vec[0])

    prefer_ccw = _heading_prefers_ccw(start_vec, start_heading) if start_heading else None
    if prefer_ccw is None and end_heading:
        prefer_ccw = _heading_prefers_ccw(end_vec, end_heading)
    if prefer_ccw is None:
        prefer_ccw = _choose_ccw_direction(start_vec, end_vec)

    angle_span = end_angle - start_angle
    if prefer_ccw:
        if angle_span <= 0:
            angle_span += 2 * math.pi
    else:
        if angle_span >= 0:
            angle_span -= 2 * math.pi

    total_angle = abs(angle_span)
    if total_angle < 1e-6:
        return [start, end]

    steps = max(8, int(total_angle / (math.pi / 36)))
    points: list[Point] = []
    for step in range(steps + 1):
        fraction = step / steps
        angle = start_angle + angle_span * fraction
        x = cx + math.cos(angle) * radius_length
        y = cy + math.sin(angle) * radius_length
        points.append((x, y))

    return points


def update_section_geometry(section: SectionPreview) -> SectionPreview:
    start_heading = section.start_heading
    end_heading = section.end_heading

    if section.sang1 is not None and section.sang2 is not None:
        start_heading = _round_heading((section.sang1, section.sang2))
    if section.eang1 is not None and section.eang2 is not None:
        end_heading = _round_heading((section.eang1, section.eang2))

    polyline = _build_section_polyline(
        section.type_name,
        section.start,
        section.end,
        section.center,
        section.radius,
        start_heading,
        end_heading,
    )
    start_heading, end_heading = _derive_heading_vectors(
        polyline, section.sang1, section.sang2, section.eang1, section.eang2
    )
    return replace(
        section,
        polyline=polyline,
        start_heading=start_heading,
        end_heading=end_heading,
    )


def _derive_heading_vectors(
    polyline: list[Point],
    sang1: float | None,
    sang2: float | None,
    eang1: float | None,
    eang2: float | None,
) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    if sang1 is not None and sang2 is not None and eang1 is not None and eang2 is not None:
        return _round_heading((sang1, sang2)), _round_heading((eang1, eang2))

    if len(polyline) < 2:
        return None, None

    start = polyline[0]
    end = polyline[-1]
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = (dx * dx + dy * dy) ** 0.5
    if length <= 0:
        return None, None

    heading = (dx / length, dy / length)
    rounded = _round_heading(heading)
    return rounded, rounded


def _round_heading(vector: tuple[float, float] | None) -> tuple[float, float] | None:
    normalized = _normalize_heading(vector)
    if normalized is None:
        return None
    return (round(normalized[0], 5), round(normalized[1], 5))


def _normalize_heading(vector: tuple[float, float] | None) -> tuple[float, float] | None:
    if vector is None:
        return None

    length = (vector[0] * vector[0] + vector[1] * vector[1]) ** 0.5
    if length <= 0:
        return None

    return (vector[0] / length, vector[1] / length)


# Delayed import to avoid circular dependency
from icr2_core.trk.trk_utils import get_cline_pos  # noqa: E402  pylint: disable=C0413
