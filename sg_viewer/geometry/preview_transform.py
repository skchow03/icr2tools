from __future__ import annotations

from typing import Tuple

from sg_viewer.model import preview_state

Point = Tuple[float, float]
Bounds = tuple[float, float, float, float]
Transform = tuple[float, tuple[float, float]]

MILE_IN_500THS = 63_360 * 500
DEFAULT_VIEW_HALF_SPAN_500THS = MILE_IN_500THS  # 1 mile to either side = 2 miles wide


def default_bounds() -> Bounds:
    half_span = float(DEFAULT_VIEW_HALF_SPAN_500THS)
    return (-half_span, half_span, -half_span, half_span)


def apply_default_bounds(bounds: Bounds | None) -> Bounds:
    return bounds or default_bounds()


def combine_bounds(bounds: Bounds | None, background_bounds: Bounds | None) -> Bounds | None:
    if bounds and background_bounds:
        min_x = min(bounds[0], background_bounds[0])
        max_x = max(bounds[1], background_bounds[1])
        min_y = min(bounds[2], background_bounds[2])
        max_y = max(bounds[3], background_bounds[3])
        return (min_x, max_x, min_y, max_y)

    return bounds or background_bounds


def active_bounds(bounds: Bounds | None, background_bounds: Bounds | None = None) -> Bounds:
    combined = combine_bounds(bounds, background_bounds)
    return apply_default_bounds(combined)


def calculate_fit_scale(bounds: Bounds | None, widget_size: tuple[int, int]) -> float | None:
    active = apply_default_bounds(bounds)
    return preview_state.calculate_fit_scale(active, widget_size)


def fit_view(
    sampled_bounds: Bounds | None, background_bounds: Bounds | None, widget_size: tuple[int, int]
) -> tuple[float, Point, Bounds] | None:
    if background_bounds is None:
        return None

    active = active_bounds(sampled_bounds, background_bounds)
    fit_scale = preview_state.calculate_fit_scale(active, widget_size)
    if fit_scale is None:
        return None

    center = preview_state.default_center(active)
    if center is None:
        return None

    return fit_scale, center, active


def update_fit_scale(
    state: preview_state.TransformState, bounds: Bounds | None, widget_size: tuple[int, int]
) -> preview_state.TransformState:
    active = apply_default_bounds(bounds)
    default_center_value = preview_state.default_center(active)
    return preview_state.update_fit_scale(state, active, widget_size, default_center_value)


def current_transform(
    state: preview_state.TransformState, bounds: Bounds | None, widget_size: tuple[int, int]
) -> tuple[Transform | None, preview_state.TransformState]:
    active = apply_default_bounds(bounds)
    default_center_value = preview_state.default_center(active)
    return preview_state.current_transform(state, active, widget_size, default_center_value)
