"""Pan and zoom helpers for the SG preview widget."""
from __future__ import annotations

from dataclasses import replace
from typing import Callable, Tuple

from sg_viewer.models import preview_state

Point = Tuple[float, float]
Transform = tuple[float, tuple[float, float]]


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
