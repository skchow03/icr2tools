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
class CurveMarker:
    center: Point
    start: Point
    end: Point
    radius: float


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
    curve_markers: dict[int, CurveMarker]
    section_endpoints: list[tuple[Point, Point]]
    status_message: str


@dataclass(frozen=True)
class TransformState:
    fit_scale: float | None = None
    current_scale: float | None = None
    view_center: Point | None = None
    user_transform_active: bool = False


def _build_preview(sgfile: SGFile, trk: TRKFile, path: Path | None = None) -> PreviewData:
    cline = get_cline_pos(trk)
    sampled, sampled_dlongs, bounds = sample_centerline(trk, cline)

    if not sampled or bounds is None:
        raise ValueError("Failed to build centreline from SG file")

    centerline_index = build_centerline_index(sampled, bounds)
    track_length = float(trk.trklength)
    curve_markers = _build_curve_markers(trk, cline, track_length)
    section_endpoints = _build_section_endpoints(trk, cline, track_length)

    status_message = f"Loaded {path.name}" if path else "Loaded SG data"

    return PreviewData(
        sgfile=sgfile,
        trk=trk,
        cline=cline,
        sampled_centerline=sampled,
        sampled_dlongs=sampled_dlongs,
        sampled_bounds=bounds,
        centerline_index=centerline_index,
        track_length=track_length,
        curve_markers=curve_markers,
        section_endpoints=section_endpoints,
        status_message=status_message,
    )


def load_preview(path: Path) -> PreviewData:
    sgfile = SGFile.from_sg(str(path))
    trk = TRKFile.from_sg(str(path))
    return _build_preview(sgfile, trk, path)


def load_preview_from_objects(sgfile: SGFile, trk: TRKFile, path: Path | None) -> PreviewData:
    """Build PreviewData from in-memory SG/TRK objects."""

    return _build_preview(sgfile, trk, path)


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


def _build_curve_markers(
    trk: TRKFile, cline: Iterable[Point] | None, track_length: float
) -> dict[int, CurveMarker]:
    markers: dict[int, CurveMarker] = {}

    if track_length <= 0:
        return markers

    for idx, sect in enumerate(trk.sects):
        if getattr(sect, "type", None) != 2:
            continue
        if hasattr(sect, "center_x") and hasattr(sect, "center_y"):
            center = (float(sect.center_x), float(sect.center_y))
        elif hasattr(sect, "ang1") and hasattr(sect, "ang2"):
            center = (float(sect.ang1), float(sect.ang2))
        else:
            continue

        if cline:
            start_x, start_y, _ = getxyz(trk, float(sect.start_dlong) % track_length, 0, cline)
            end_dlong = float(sect.start_dlong + sect.length)
            end_dlong = end_dlong % track_length if track_length else end_dlong
            end_x, end_y, _ = getxyz(trk, end_dlong, 0, cline)
            start = (start_x, start_y)
            end = (end_x, end_y)
        else:
            start = (
                float(getattr(sect, "start_x", 0.0)),
                float(getattr(sect, "start_y", 0.0)),
            )
            end = (
                float(getattr(sect, "end_x", 0.0)),
                float(getattr(sect, "end_y", 0.0)),
            )
        radius = ((start[0] - center[0]) ** 2 + (start[1] - center[1]) ** 2) ** 0.5
        markers[idx] = CurveMarker(center=center, start=start, end=end, radius=radius)
    return markers


def _build_section_endpoints(
    trk: TRKFile, cline: Iterable[Point] | None, track_length: float
) -> list[tuple[Point, Point]]:
    endpoints: list[tuple[Point, Point]] = []

    if cline is None or track_length <= 0:
        return endpoints

    for sect in trk.sects:
        start_dlong = float(sect.start_dlong) % track_length
        end_dlong = float(sect.start_dlong + sect.length) % track_length

        start_x, start_y, _ = getxyz(trk, start_dlong, 0, cline)
        end_x, end_y, _ = getxyz(trk, end_dlong, 0, cline)
        endpoints.append(((start_x, start_y), (end_x, end_y)))

    return endpoints


# Delayed import to avoid circular dependency
from icr2_core.trk.trk_utils import get_cline_pos  # noqa: E402  pylint: disable=C0413
