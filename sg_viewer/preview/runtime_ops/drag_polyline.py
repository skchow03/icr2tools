from __future__ import annotations

from PyQt5 import QtCore

from sg_viewer.preview.runtime_ops.base import Point, Transform


class _RuntimeCoreDragPolylineMixin:
    def current_transform(self, widget_size: tuple[int, int]) -> Transform | None:
        if self._drag_transform_active:
            return self._drag_transform
        return self._controller.current_transform(widget_size)

    def begin_drag_transform(self, transform: Transform) -> None:
        self._drag_transform = transform
        self._drag_transform_active = True

    def end_drag_transform(self) -> None:
        self._drag_transform = None
        self._drag_transform_active = False

    def map_to_track(
        self,
        screen_pos: tuple[float, float] | Point,
        widget_size: tuple[int, int],
        widget_height: int,
        transform: Transform | None = None,
    ) -> Point | None:
        if transform is None and self._drag_transform_active:
            transform = self._drag_transform
        point = (
            QtCore.QPointF(*screen_pos)
            if isinstance(screen_pos, tuple)
            else QtCore.QPointF(screen_pos)
        )
        return self._controller.map_to_track(point, widget_size, widget_height, transform)

    def _map_to_track_cb(
        self,
        point: Point,
        widget_size: tuple[int, int],
        widget_height: int,
        transform: Transform | None,
    ) -> Point | None:
        return self._controller.map_to_track(
            QtCore.QPointF(*point), widget_size, widget_height, transform
        )
