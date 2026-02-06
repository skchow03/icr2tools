"""Pan and zoom helpers for the SG preview widget."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Tuple

from sg_viewer.models import preview_state

Point = Tuple[float, float]
Transform = tuple[float, tuple[float, float]]


@dataclass(frozen=True)
class ViewTransform:
    scale: float
    offset: Point

    def world_to_screen(self, p: Point) -> Point:
        return (
            self.offset[0] + p[0] * self.scale,
            self.offset[1] - p[1] * self.scale,
        )

    def screen_to_world(self, p: Point) -> Point:
        if self.scale == 0:
            return (0.0, 0.0)
        return (
            (p[0] - self.offset[0]) / self.scale,
            (self.offset[1] - p[1]) / self.scale,
        )


def fit_to_bounds(
    bounds: tuple[float, float, float, float],
    viewport_size: Point,
) -> ViewTransform:
    min_x, max_x, min_y, max_y = bounds
    width = max_x - min_x
    height = max_y - min_y
    view_w, view_h = viewport_size

    if width <= 0 or height <= 0 or view_w <= 0 or view_h <= 0:
        return ViewTransform(scale=1.0, offset=(view_w * 0.5, view_h * 0.5))

    scale = min(view_w / width, view_h / height) * 0.95
    center_x = (min_x + max_x) * 0.5
    center_y = (min_y + max_y) * 0.5
    offset_x = view_w * 0.5 - center_x * scale
    offset_y = view_h * 0.5 + center_y * scale
    return ViewTransform(scale=scale, offset=(offset_x, offset_y))


def pan(transform: ViewTransform, dx: float, dy: float) -> ViewTransform:
    return ViewTransform(
        scale=transform.scale,
        offset=(transform.offset[0] + dx, transform.offset[1] + dy),
    )


def zoom(transform: ViewTransform, factor: float, anchor_point: Point) -> ViewTransform:
    if factor == 0:
        return transform
    new_scale = transform.scale * factor
    if new_scale == 0:
        return transform

    world_anchor = transform.screen_to_world(anchor_point)
    offset_x = anchor_point[0] - world_anchor[0] * new_scale
    offset_y = anchor_point[1] + world_anchor[1] * new_scale
    return ViewTransform(scale=new_scale, offset=(offset_x, offset_y))


def zoom_transform_state(
    state: preview_state.TransformState,
    delta_y: int,
    cursor_pos: Point,
    widget_size: tuple[int, int],
    widget_height: int,
    transform: Transform | None,
    clamp_scale: Callable[[float], float],
    default_center: Callable[[], Point | None],
    map_to_track: Callable[[Point], Point | None],
) -> preview_state.TransformState | None:
    """Return an updated transform state after a mouse wheel event.

    ``cursor_pos`` is a screen-space point. ``map_to_track`` converts the cursor
    to world coordinates; it should handle ``transform`` internally. ``clamp_scale``
    constrains the new scale value. ``default_center`` supplies a fallback
    world-space center when none is set.
    """

    if transform is None:
        return None

    if state.current_scale is None:
        return None

    delta = delta_y
    factor = 1.15 if delta > 0 else 1 / 1.15
    new_scale = clamp_scale(state.current_scale * factor)
    center = state.view_center or default_center()
    cursor_track = map_to_track(cursor_pos)
    if cursor_track is None:
        cursor_track = center
    if center is None or cursor_track is None:
        return None
    w, h = widget_size
    px, py = cursor_pos
    cx = cursor_track[0] - (px - w / 2) / new_scale
    cy = cursor_track[1] + (py - h / 2) / new_scale
    return replace(
        state,
        current_scale=new_scale,
        view_center=(cx, cy),
        user_transform_active=True,
    )


def pan_transform_state(
    state: preview_state.TransformState,
    delta: Point,
    scale: float,
    center: Point,
) -> preview_state.TransformState:
    """Return an updated transform state after a pan drag.

    ``delta`` is a screen-space ``(dx, dy)`` tuple; ``center`` is the current
    world-space view center.
    """

    cx, cy = center
    cx -= delta[0] / scale
    cy += delta[1] / scale
    return replace(state, view_center=(cx, cy))
