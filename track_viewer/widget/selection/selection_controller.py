"""Selection and hit-testing logic for the track preview widget."""
from __future__ import annotations

import math

from PyQt5 import QtCore

from track_viewer import rendering
from track_viewer.model.track_preview_model import TrackPreviewModel
from track_viewer.model.view_state import TrackPreviewViewState
from track_viewer.widget.interaction import InteractionCallbacks, PreviewIntent


class SelectionController:
    """Handles hit-testing and selection updates."""

    def __init__(
        self,
        model: TrackPreviewModel,
        camera_service,
        state: TrackPreviewViewState,
        callbacks: InteractionCallbacks,
    ) -> None:
        self._model = model
        self._camera_service = camera_service
        self._state = state
        self._callbacks = callbacks

    def emit_selected_camera(self) -> None:
        selected = None
        index = self._state.selected_camera
        if index is not None and 0 <= index < len(self._camera_service.cameras):
            selected = self._camera_service.cameras[index]
        self._callbacks.selected_camera_changed(index, selected)

    def set_selected_camera(self, index: int | None) -> None:
        if index is not None and (index < 0 or index >= len(self._camera_service.cameras)):
            index = None
        if index == self._state.selected_camera:
            return
        self._state.selected_camera = index
        self.emit_selected_camera()
        self._callbacks.state_changed(PreviewIntent.SELECTION_CHANGED)

    def set_selected_flag(self, index: int | None) -> None:
        if index is not None and (index < 0 or index >= len(self._state.flags)):
            index = None
        if index == self._state.selected_flag:
            return
        self._state.selected_flag = index
        coords = None
        if index is not None and 0 <= index < len(self._state.flags):
            coords = self._state.flags[index]
        self._callbacks.selected_flag_changed(coords)
        self._callbacks.state_changed(PreviewIntent.SELECTION_CHANGED)

    def select_lp_record(self, name: str, index: int) -> None:
        if self._state.selected_lp_line == name and self._state.selected_lp_index == index:
            return
        self._state.selected_lp_line = name
        self._state.selected_lp_index = index
        self._callbacks.lp_record_selected(name, index)
        self._callbacks.state_changed(PreviewIntent.SELECTION_CHANGED)

    def camera_at_point(self, point: QtCore.QPointF, size: QtCore.QSize) -> int | None:
        transform = self._state.current_transform(self._model.bounds, size)
        if not transform:
            return None
        hit_radius = 16.0
        allowed_indices = None
        if self._state.show_cameras_current_tv_only:
            allowed_indices = self._camera_service.camera_indices_for_view(
                self._state.current_tv_mode_index
            )
        for index, cam in enumerate(self._camera_service.cameras):
            if allowed_indices is not None and index not in allowed_indices:
                continue
            camera_point = rendering.map_point(cam.x, cam.y, transform, size.height())
            if (
                math.hypot(
                    camera_point.x() - point.x(),
                    camera_point.y() - point.y(),
                )
                <= hit_radius
            ):
                return index
        return None

    def flag_at_point(self, point: QtCore.QPointF, size: QtCore.QSize) -> int | None:
        transform = self._state.current_transform(self._model.bounds, size)
        if not transform:
            return None
        for index, (fx, fy) in enumerate(self._state.flags):
            flag_point = rendering.map_point(fx, fy, transform, size.height())
            if (flag_point - point).manhattanLength() <= 8:
                return index
        return None

    def lp_record_at_point(
        self, point: QtCore.QPointF, lp_name: str, size: QtCore.QSize
    ) -> int | None:
        records = self._model.ai_line_records(lp_name)
        if not records:
            return None
        transform = self._state.current_transform(self._model.bounds, size)
        if not transform:
            return None
        cursor_track = self._state.map_to_track(point, self._model.bounds, size)
        if cursor_track is None:
            return None

        cursor_x, cursor_y = cursor_track
        best_point = None
        best_distance_sq = math.inf
        best_start_index = None
        best_end_index = None

        for idx in range(len(records)):
            p0 = records[idx]
            p1 = records[(idx + 1) % len(records)]
            seg_dx = p1.x - p0.x
            seg_dy = p1.y - p0.y
            seg_len_sq = seg_dx * seg_dx + seg_dy * seg_dy
            if seg_len_sq == 0:
                continue
            t = ((cursor_x - p0.x) * seg_dx + (cursor_y - p0.y) * seg_dy) / seg_len_sq
            t = max(0.0, min(1.0, t))
            proj_x = p0.x + seg_dx * t
            proj_y = p0.y + seg_dy * t
            dist_sq = (cursor_x - proj_x) ** 2 + (cursor_y - proj_y) ** 2
            if dist_sq < best_distance_sq:
                best_distance_sq = dist_sq
                best_point = (proj_x, proj_y)
                best_start_index = idx
                best_end_index = (idx + 1) % len(records)

        if best_point is None or best_start_index is None or best_end_index is None:
            return None

        mapped_point = rendering.map_point(
            best_point[0], best_point[1], transform, size.height()
        )
        if (mapped_point - point).manhattanLength() > 16:
            return None

        start_record = records[best_start_index]
        end_record = records[best_end_index]
        dist_start = (cursor_x - start_record.x) ** 2 + (cursor_y - start_record.y) ** 2
        dist_end = (cursor_x - end_record.x) ** 2 + (cursor_y - end_record.y) ** 2
        return best_start_index if dist_start <= dist_end else best_end_index
