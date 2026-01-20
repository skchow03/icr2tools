from __future__ import annotations

from dataclasses import replace
from typing import Callable

from PyQt5 import QtGui

from sg_viewer.geometry import preview_transform
from sg_viewer.models import preview_state
from sg_viewer.preview.transform import pan_transform_state, zoom_transform_state
from sg_viewer.ui.preview_viewport import PreviewViewport

Point = tuple[float, float]
Transform = tuple[float, tuple[float, float]]


class TransformController:
    def __init__(
        self,
        viewport: PreviewViewport,
        get_state: Callable[[], preview_state.TransformState],
        set_state: Callable[[preview_state.TransformState], None],
        map_to_track_cb: Callable[[Point, tuple[int, int], int, Transform | None], Point | None],
    ) -> None:
        self._viewport = viewport
        self._get_state = get_state
        self._set_state = set_state
        self._map_to_track_cb = map_to_track_cb
        self._last_bounds: tuple[float, float, float, float] | None = None
        self._is_panning = False
        self._last_pan_pos: Point | None = None

    def update_fit_scale(
        self, sampled_bounds: tuple[float, float, float, float] | None, widget_size: tuple[int, int]
    ) -> None:
        self._last_bounds = sampled_bounds
        self._viewport.update_fit_scale(sampled_bounds, widget_size)

    def fit_view_to_background(
        self, sampled_bounds: tuple[float, float, float, float] | None, widget_size: tuple[int, int]
    ) -> tuple[float, float, float, float] | None:
        active_bounds = self._viewport.fit_view_to_background(sampled_bounds, widget_size)
        if active_bounds is not None:
            self._last_bounds = active_bounds
        return active_bounds

    def clamp_scale(self, scale: float) -> float:
        return preview_state.clamp_scale(scale, self._get_state())

    def set_user_transform_active(self) -> None:
        self._set_state(replace(self._get_state(), user_transform_active=True))

    def _default_center(self) -> Point | None:
        active = preview_transform.apply_default_bounds(self._last_bounds)
        return preview_state.default_center(active)

    def lock_user_transform(self, widget_size: tuple[int, int]) -> None:
        state = self._get_state()
        if state.user_transform_active:
            return

        if state.current_scale is None or state.view_center is None:
            if self._last_bounds is not None:
                self.update_fit_scale(self._last_bounds, widget_size)
                state = self._get_state()

        self._set_state(
            replace(
                state,
                user_transform_active=True,
                current_scale=state.current_scale or state.fit_scale,
            )
        )

    def on_wheel(
        self,
        event: QtGui.QWheelEvent,
        *,
        widget_size: tuple[int, int],
        widget_height: int,
        transform: Transform | None,
    ) -> bool:
        state = self._get_state()
        new_state = zoom_transform_state(
            state,
            event.angleDelta().y(),
            (event.pos().x(), event.pos().y()),
            widget_size,
            widget_height,
            transform,
            self.clamp_scale,
            self._default_center,
            lambda p: self._map_to_track_cb(p, widget_size, widget_height, transform),
        )
        if new_state is None:
            return False
        self._set_state(new_state)
        return True

    def begin_pan(self, pos: Point) -> None:
        self._is_panning = True
        self._last_pan_pos = pos
        self.set_user_transform_active()

    def update_pan(self, pos: Point) -> bool:
        if not self._is_panning or self._last_pan_pos is None:
            return False

        state = self._get_state()
        scale = state.current_scale or state.fit_scale
        if scale is None:
            return False

        center = state.view_center or self._default_center()
        if center is None:
            return False

        delta = (pos[0] - self._last_pan_pos[0], pos[1] - self._last_pan_pos[1])
        self._last_pan_pos = pos
        self._set_state(pan_transform_state(state, delta, scale, center))
        return True

    def end_pan(self) -> None:
        self._is_panning = False
        self._last_pan_pos = None
