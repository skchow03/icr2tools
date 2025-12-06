from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Tuple

Point = Tuple[float, float]
Transform = tuple[float, tuple[float, float]]


@dataclass(frozen=True)
class TransformState:
    fit_scale: float | None = None
    current_scale: float | None = None
    view_center: Point | None = None
    user_transform_active: bool = False


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
    fit_scale = calculate_fit_scale(sampled_bounds, widget_size)
    if fit_scale is None:
        return state

    if state.user_transform_active:
        return state

    return replace(
        state,
        fit_scale=fit_scale,
        current_scale=fit_scale,
        view_center=state.view_center or default_center_value,
    )


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


def map_to_track(transform: Transform | None, point: tuple[float, float], widget_height: int) -> Point | None:
    if not transform:
        return None
    scale, offsets = transform
    x = (point[0] - offsets[0]) / scale
    py = widget_height - point[1]
    y = (py - offsets[1]) / scale
    return x, y
