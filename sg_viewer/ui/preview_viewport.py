from __future__ import annotations

from dataclasses import replace
from typing import Callable, Tuple

from sg_viewer.geometry import preview_transform
from sg_viewer.services.preview_background import PreviewBackground
from sg_viewer.models import preview_state

Point = Tuple[float, float]


class PreviewViewport:
    def __init__(
        self,
        *,
        background: PreviewBackground,
        get_transform_state: Callable[[], preview_state.TransformState],
        set_transform_state: Callable[[preview_state.TransformState], None],
    ) -> None:
        self._background = background
        self._get_transform_state = get_transform_state
        self._set_transform_state = set_transform_state

    @staticmethod
    def default_bounds() -> tuple[float, float, float, float]:
        return preview_transform.default_bounds()

    def update_fit_scale(
        self,
        sampled_bounds: tuple[float, float, float, float] | None,
        widget_size: Tuple[int, int],
    ) -> None:
        new_state = preview_transform.update_fit_scale(
            self._get_transform_state(), sampled_bounds, widget_size
        )
        self._set_transform_state(new_state)

    def combine_bounds_with_background(
        self, bounds: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        return preview_transform.active_bounds(bounds, self._background.bounds())

    def fit_view_to_background(
        self,
        sampled_bounds: tuple[float, float, float, float] | None,
        widget_size: Tuple[int, int],
    ) -> tuple[float, float, float, float] | None:
        result = self._background.fit_view(sampled_bounds, widget_size)
        if result is None:
            return None

        fit_scale, center, active_bounds = result
        self._set_transform_state(
            replace(
                self._get_transform_state(),
                fit_scale=fit_scale,
                current_scale=fit_scale,
                view_center=center,
                user_transform_active=False,
            )
        )
        return active_bounds
