from __future__ import annotations

from dataclasses import dataclass, replace

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


@dataclass(frozen=True)
class TransformState:
    fit_scale: float | None = None
    current_scale: float | None = None
    view_center: Point | None = None
    user_transform_active: bool = False


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


def default_center(sampled_bounds: tuple[float, float, float, float] | None) -> Point | None:
    if not sampled_bounds:
        return None
    min_x, max_x, min_y, max_y = sampled_bounds
    return ((min_x + max_x) / 2, (min_y + max_y) / 2)


def calculate_fit_scale(
    sampled_bounds: tuple[float, float, float, float] | None, widget_size: tuple[int, int]
) -> float | None:
    if not sampled_bounds:
        return None
    min_x, max_x, min_y, max_y = sampled_bounds
    span_x = max_x - min_x
    span_y = max_y - min_y
    if span_x <= 0 or span_y <= 0:
        return None
    margin = 24
    w, h = widget_size
    available_w = max(w - margin * 2, 1)
    available_h = max(h - margin * 2, 1)
    scale_x = available_w / span_x
    scale_y = available_h / span_y
    return min(scale_x, scale_y)


def update_fit_scale(
    state: TransformState,
    sampled_bounds: tuple[float, float, float, float] | None,
    widget_size: tuple[int, int],
    default_center_value: Point | None,
) -> TransformState:
    fit = calculate_fit_scale(sampled_bounds, widget_size)
    new_state = replace(state, fit_scale=fit)
    if fit is not None and not state.user_transform_active:
        new_state = replace(new_state, current_scale=fit)
        if state.view_center is None and default_center_value is not None:
            new_state = replace(new_state, view_center=default_center_value)
    return new_state


def current_transform(
    state: TransformState,
    sampled_bounds: tuple[float, float, float, float] | None,
    widget_size: tuple[int, int],
    default_center_value: Point | None,
) -> tuple[Transform | None, TransformState]:
    if not sampled_bounds:
        return None, state

    updated_state = state
    if state.current_scale is None:
        updated_state = update_fit_scale(state, sampled_bounds, widget_size, default_center_value)

    scale = updated_state.current_scale
    center = updated_state.view_center or default_center_value
    if scale is None or center is None:
        return None, updated_state

    w, h = widget_size
    offsets = (w / 2 - center[0] * scale, h / 2 - center[1] * scale)
    return (scale, offsets), updated_state


def clamp_scale(scale: float, state: TransformState) -> float:
    base = state.fit_scale or state.current_scale or 1.0
    min_scale = base * 0.1
    max_scale = base * 25.0
    return max(min_scale, min(max_scale, scale))


def _build_sections(
    sgfile: SGFile, trk: TRKFile, cline: Iterable[Point] | None, track_length: float
) -> list[SectionPreview]:
    sections: list[SectionPreview] = []

    if cline is None or track_length <= 0:
        return sections

    for idx, (sg_sect, trk_sect) in enumerate(zip(sgfile.sects, trk.sects)):
        start_dlong = float(trk_sect.start_dlong) % track_length
        length = float(trk_sect.length)
        polyline = _sample_section_polyline(trk, cline, track_length, start_dlong, length)

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


def _sample_section_polyline(
    trk: TRKFile,
    cline: Iterable[Point],
    track_length: float,
    start_dlong: float,
    length: float,
) -> list[Point]:
    step = 5000.0
    remaining = float(length)
    current = float(start_dlong)
    points: list[Point] = []

    while remaining > 0:
        x, y, _ = getxyz(trk, current % track_length, 0, cline)
        points.append((x, y))
        advance = min(step, remaining)
        current += advance
        remaining -= advance

    end_dlong = (start_dlong + length) % track_length if track_length else start_dlong + length
    x, y, _ = getxyz(trk, end_dlong, 0, cline)
    points.append((x, y))
    return points


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
