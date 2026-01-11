"""Mouse interaction logic for the track preview widget."""
from __future__ import annotations

import math

from PyQt5 import QtCore, QtGui

from icr2_core.trk.trk_utils import getxyz
from track_viewer import rendering
from track_viewer.common.weather_compass import (
    heading_adjust_to_turns,
    turns_from_vector,
    turns_to_heading_adjust,
    turns_to_wind_direction,
    turns_to_unit_vector,
)
from track_viewer.geometry import project_point_to_centerline
from track_viewer.model.track_preview_model import TrackPreviewModel
from track_viewer.model.view_state import TrackPreviewViewState
from track_viewer.widget.editing.camera_edit_controller import CameraEditController
from track_viewer.widget.editing.flag_edit_controller import FlagEditController
from track_viewer.widget.editing.lp_edit_controller import LpEditController
from track_viewer.widget.interaction import InteractionCallbacks, PreviewIntent
from track_viewer.widget.selection.selection_controller import SelectionController


class TrackPreviewMouseController:
    """Encapsulates mouse logic and projection handling."""

    def __init__(
        self,
        model: TrackPreviewModel,
        state: TrackPreviewViewState,
        callbacks: InteractionCallbacks,
        selection: SelectionController,
        camera_edit: CameraEditController,
        flag_edit: FlagEditController,
        lp_edit: LpEditController,
    ) -> None:
        self._model = model
        self._state = state
        self._callbacks = callbacks
        self._selection = selection
        self._camera_edit = camera_edit
        self._flag_edit = flag_edit
        self._lp_edit = lp_edit
        self._lp_hover_timer = QtCore.QTimer()
        self._lp_hover_timer.setInterval(24)
        self._lp_hover_timer.setTimerType(QtCore.Qt.PreciseTimer)
        self._lp_hover_timer.timeout.connect(self._process_lp_hover)
        self._pending_lp_hover_point: QtCore.QPointF | None = None
        self._pending_lp_hover_size: QtCore.QSize | None = None
        self._lp_hover_dirty = False

    def handle_wheel(self, event: QtGui.QWheelEvent, size: QtCore.QSize) -> bool:
        if self._state.current_scale is None:
            self._state.current_scale = self._state.fit_scale or 1.0
        delta = event.angleDelta().y()
        if delta == 0:
            return False
        if self._state.view_center is None:
            self._state.view_center = self._state.default_center(self._model.bounds)
        if self._state.view_center is None or self._state.current_scale is None:
            return False
        factor = 1.15 if delta > 0 else 1 / 1.15
        new_scale = self._state.clamp_scale(self._state.current_scale * factor)
        cursor_track = self._state.map_to_track(event.pos(), self._model.bounds, size)
        if cursor_track is None:
            cursor_track = self._state.view_center
        w, h = size.width(), size.height()
        px, py = event.pos().x(), event.pos().y()
        cx = cursor_track[0] - (px - w / 2) / new_scale
        cy = cursor_track[1] + (py - h / 2) / new_scale
        self._state.view_center = (cx, cy)
        self._state.current_scale = new_scale
        self._state.user_transform_active = True
        self._callbacks.state_changed(PreviewIntent.VIEW_TRANSFORM_CHANGED)
        return True

    def handle_mouse_press(self, event: QtGui.QMouseEvent, size: QtCore.QSize) -> bool:
        if event.button() == QtCore.Qt.RightButton and self._model.surface_mesh:
            if self._camera_edit.handle_camera_drag_press(event.pos(), size):
                return True
            if self._flag_edit.remove_flag_at_point(event.pos(), size):
                return True

        if event.button() == QtCore.Qt.LeftButton:
            if self._handle_weather_compass_press(event.pos(), size):
                return True
            self._callbacks.diagram_clicked()
            if self._model.surface_mesh and self._camera_edit.select_camera_at_point(
                event.pos(), size
            ):
                return True
            if self._model.surface_mesh and self._flag_edit.handle_flag_press(
                event.pos(), size
            ):
                return True
            self._state.is_panning = True
            self._state.last_mouse_pos = event.pos()
            self._state.left_press_pos = event.pos()
            self._state.dragged_during_press = False
            self._state.user_transform_active = True
            return True
        return False

    def handle_mouse_move(self, event: QtGui.QMouseEvent, size: QtCore.QSize) -> bool:
        if self._state.dragging_weather_compass is not None:
            self._update_weather_compass_heading(event.pos(), size)
            return True
        handled = False
        if self._state.dragging_camera_index is not None:
            self._camera_edit.update_camera_position(event.pos(), size)
            handled = True
        if self._state.dragging_flag_index is not None:
            self._flag_edit.update_flag_position(event.pos(), size)
            handled = True
        if self._state.is_panning and self._state.last_mouse_pos is not None:
            transform = self._state.current_transform(self._model.bounds, size)
            if transform:
                if self._state.view_center is None:
                    self._state.view_center = self._state.default_center(
                        self._model.bounds
                    )
                if self._state.view_center is not None:
                    scale, _ = transform
                    delta = event.pos() - self._state.last_mouse_pos
                    self._state.last_mouse_pos = event.pos()
                    if (
                        not self._state.dragged_during_press
                        and self._state.left_press_pos is not None
                        and (event.pos() - self._state.left_press_pos).manhattanLength()
                        > 4
                    ):
                        self._state.dragged_during_press = True
                    cx, cy = self._state.view_center
                    cx -= delta.x() / scale
                    cy += delta.y() / scale
                    self._state.view_center = (cx, cy)
                    self._callbacks.state_changed(PreviewIntent.VIEW_TRANSFORM_CHANGED)
            handled = True
        self._update_cursor_position(event.pos(), size)
        self._queue_lp_hover_update(event.pos(), size)
        return handled

    def handle_mouse_release(
        self, event: QtGui.QMouseEvent, size: QtCore.QSize
    ) -> bool:
        if event.button() == QtCore.Qt.LeftButton:
            if self._state.dragging_weather_compass is not None:
                self._state.dragging_weather_compass = None
                self._update_cursor_position(event.pos(), size)
                return True
            if self._state.dragging_camera_index is not None:
                self._camera_edit.end_camera_drag()
                self._update_cursor_position(event.pos(), size)
                return True
            if self._state.dragging_flag_index is not None:
                self._flag_edit.end_flag_drag()
                self._update_cursor_position(event.pos(), size)
                return True
            click_without_drag = not self._state.dragged_during_press
            self._state.is_panning = False
            self._state.last_mouse_pos = None
            self._state.left_press_pos = None
            self._state.dragged_during_press = False
            if click_without_drag and self._model.surface_mesh:
                self._handle_primary_click(event.pos(), size)
            self._update_cursor_position(event.pos(), size)
            return True
        if event.button() == QtCore.Qt.RightButton:
            if self._state.dragging_camera_index is not None:
                self._camera_edit.end_camera_drag()
                self._update_cursor_position(event.pos(), size)
                return True
        return False

    def _queue_lp_hover_update(
        self, point: QtCore.QPointF, size: QtCore.QSize
    ) -> None:
        if not self._should_update_lp_hover():
            self._clear_lp_hover_update()
            return
        self._pending_lp_hover_point = QtCore.QPointF(point)
        self._pending_lp_hover_size = QtCore.QSize(size)
        self._lp_hover_dirty = True
        if not self._lp_hover_timer.isActive():
            self._lp_hover_timer.start()

    def _clear_lp_hover_update(self) -> None:
        self._lp_hover_dirty = False
        self._pending_lp_hover_point = None
        self._pending_lp_hover_size = None
        if self._lp_hover_timer.isActive():
            self._lp_hover_timer.stop()

    def _should_update_lp_hover(self) -> bool:
        if (
            self._state.is_panning
            or self._state.dragging_weather_compass is not None
            or self._state.dragging_camera_index is not None
            or self._state.dragging_flag_index is not None
        ):
            return False
        active_line = self._state.active_lp_line or "center-line"
        if active_line == "center-line":
            return False
        if active_line not in self._model.visible_lp_files:
            return False
        return True

    def _process_lp_hover(self) -> None:
        if not self._lp_hover_dirty:
            self._lp_hover_timer.stop()
            return
        self._lp_hover_dirty = False
        if not self._should_update_lp_hover():
            return
        point = self._pending_lp_hover_point
        size = self._pending_lp_hover_size
        if point is None or size is None:
            return
        active_line = self._state.active_lp_line or "center-line"
        lp_index = self._selection.lp_record_at_point(point, active_line, size)
        if lp_index is None:
            return
        if (
            self._state.selected_lp_line == active_line
            and self._state.selected_lp_index == lp_index
        ):
            return
        self._selection.select_lp_record(active_line, lp_index)

    def handle_leave(self) -> None:
        self._clear_lp_hover_update()
        self._state.dragging_weather_compass = None
        cursor_changed = self._state.set_cursor_position(None)
        if cursor_changed:
            self._callbacks.cursor_position_changed(None)
        projection_changed = self._state.set_projection_data(
            None, None, None, None, None, None, None
        )
        if cursor_changed or projection_changed:
            self._callbacks.state_changed(PreviewIntent.PROJECTION_CHANGED)

    def _update_cursor_position(self, point: QtCore.QPointF, size: QtCore.QSize) -> None:
        if (
            self._state.is_panning
            or self._state.dragging_weather_compass is not None
            or self._state.dragging_camera_index is not None
            or self._state.dragging_flag_index is not None
        ):
            return
        if not self._model.surface_mesh or not self._model.bounds:
            cursor_changed = self._state.set_cursor_position(None)
            if cursor_changed:
                self._callbacks.cursor_position_changed(None)
            projection_changed = self._state.set_projection_data(
                None, None, None, None, None, None, None
            )
            if cursor_changed or projection_changed:
                self._callbacks.state_changed(PreviewIntent.PROJECTION_CHANGED)
            return
        coords = self._state.map_to_track(point, self._model.bounds, size)
        cursor_changed = self._state.set_cursor_position(coords)
        if cursor_changed:
            self._callbacks.cursor_position_changed(coords)
        projection_changed = self._update_active_line_projection(point, size)
        if cursor_changed or projection_changed:
            self._callbacks.state_changed(PreviewIntent.PROJECTION_CHANGED)

    def _handle_weather_compass_press(
        self, point: QtCore.QPointF, size: QtCore.QSize
    ) -> bool:
        if not self._state.show_weather_compass:
            return False
        center = self._state.weather_compass_center(size)
        radius = self._state.weather_compass_radius(size)
        handle_radius = self._state.weather_compass_handle_radius(size)
        turns = self._state.weather_compass_turns()
        dx, dy = turns_to_unit_vector(turns)
        wind_handle = QtCore.QPointF(
            center.x() + dx * radius, center.y() + dy * radius
        )
        heading_adjust = (
            self._state.wind2_heading_adjust
            if self._state.weather_compass_source == "wind2"
            else self._state.wind_heading_adjust
        )
        heading_turns = (
            heading_adjust_to_turns(heading_adjust)
            if heading_adjust is not None
            else None
        )
        heading_handle = None
        if heading_turns is not None:
            heading_dx, heading_dy = turns_to_unit_vector(heading_turns)
            heading_handle = QtCore.QPointF(
                center.x() + heading_dx * radius,
                center.y() + heading_dy * radius,
            )
        if heading_handle is not None:
            if (
                math.hypot(point.x() - heading_handle.x(), point.y() - heading_handle.y())
                <= max(10.0, handle_radius * 2.0)
            ):
                self._state.dragging_weather_compass = "heading"
                self._update_weather_compass_heading(point, size)
                return True
        if (
            math.hypot(point.x() - wind_handle.x(), point.y() - wind_handle.y())
            <= max(10.0, handle_radius * 2.5)
        ):
            self._state.dragging_weather_compass = "wind"
            self._update_weather_compass_heading(point, size)
            return True
        return False

    def _update_weather_compass_heading(
        self, point: QtCore.QPointF, size: QtCore.QSize
    ) -> None:
        center = self._state.weather_compass_center(size)
        dx = point.x() - center.x()
        dy = point.y() - center.y()
        turns = turns_from_vector(dx, dy)
        heading_adjust = (
            self._state.wind2_heading_adjust
            if self._state.weather_compass_source == "wind2"
            else self._state.wind_heading_adjust
        )
        heading_turns = (
            heading_adjust_to_turns(heading_adjust)
            if heading_adjust is not None
            else 0.0
        )
        direction = turns_to_wind_direction((turns - heading_turns) % 1.0)
        if self._state.dragging_weather_compass == "wind":
            if self._state.set_weather_wind_direction(
                self._state.weather_compass_source, direction
            ):
                self._callbacks.weather_wind_direction_changed(
                    self._state.weather_compass_source, direction
                )
                self._callbacks.state_changed(PreviewIntent.OVERLAY_CHANGED)
            return
        if self._state.dragging_weather_compass == "heading":
            adjust = turns_to_heading_adjust(turns)
            if self._state.set_weather_heading_adjust(
                self._state.weather_compass_source, adjust
            ):
                self._callbacks.weather_heading_adjust_changed(
                    self._state.weather_compass_source, adjust
                )
                self._callbacks.state_changed(PreviewIntent.OVERLAY_CHANGED)

    def _update_active_line_projection(
        self, point: QtCore.QPointF | None, size: QtCore.QSize
    ) -> bool:
        active = self._state.active_lp_line if self._state.active_lp_line else "center-line"
        if active != "center-line" and active not in self._model.available_lp_files:
            active = "center-line"
        if active == "center-line":
            return self._update_centerline_projection(point, size)
        return self._update_ai_line_projection(point, active, size)

    def _update_centerline_projection(
        self, point: QtCore.QPointF | None, size: QtCore.QSize
    ) -> bool:
        if (
            point is None
            or not self._model.sampled_centerline
            or not self._model.sampled_dlongs
            or not self._state.show_center_line
        ):
            return self._state.set_projection_data(
                None, None, None, None, None, None, None
            )

        if (
            self._state.projection_cached_point is not None
            and self._state.projection_cached_result is not None
            and (point - self._state.projection_cached_point).manhattanLength() <= 3
            and self._state.projection_cached_result[-1] == "center-line"
        ):
            (
                cached_point,
                cached_dlong,
                cached_dlat,
                cached_speed,
                cached_elevation,
                cached_acceleration,
                cached_line,
            ) = self._state.projection_cached_result
            return self._state.set_projection_data(
                cached_point,
                cached_dlong,
                cached_dlat,
                cached_speed,
                cached_elevation,
                cached_acceleration,
                cached_line,
            )

        transform = self._state.current_transform(self._model.bounds, size)
        if not transform or not self._model.trk:
            return self._state.set_projection_data(
                None, None, None, None, None, None, None
            )

        screen_bounds = rendering.centerline_screen_bounds(
            self._model.sampled_bounds, transform, size.height()
        )
        if screen_bounds:
            dx = max(
                screen_bounds.left() - point.x(),
                0.0,
                point.x() - screen_bounds.right(),
            )
            dy = max(
                screen_bounds.top() - point.y(),
                0.0,
                point.y() - screen_bounds.bottom(),
            )
            if max(dx, dy) > 24:
                self._state.projection_cached_point = point
                self._state.projection_cached_result = (
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                )
                return self._state.set_projection_data(
                    None, None, None, None, None, None, None
                )

        cursor_track = self._state.map_to_track(point, self._model.bounds, size)
        if cursor_track is None:
            return self._state.set_projection_data(
                None, None, None, None, None, None, None
            )

        if self._model.centerline_index is None:
            return self._state.set_projection_data(
                None, None, None, None, None, None, None
            )

        cursor_x, cursor_y = cursor_track
        track_length = float(self._model.trk.trklength)
        best_point, best_dlong, _ = project_point_to_centerline(
            (cursor_x, cursor_y),
            self._model.centerline_index,
            self._model.sampled_dlongs,
            track_length,
        )

        if best_point is None:
            return self._state.set_projection_data(
                None, None, None, None, None, None, None
            )
        mapped_point = rendering.map_point(
            best_point[0], best_point[1], transform, size.height()
        )
        pixel_distance = (mapped_point - point).manhattanLength()
        if pixel_distance > 16:
            self._state.projection_cached_point = point
            self._state.projection_cached_result = (
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            )
            return self._state.set_projection_data(
                None, None, None, None, None, None, None
            )
        elevation = None
        if best_dlong is not None and self._model.centerline:
            _, _, elevation = getxyz(
                self._model.trk, float(best_dlong), 0, self._model.centerline
            )
        self._state.projection_cached_point = point
        self._state.projection_cached_result = (
            best_point,
            best_dlong,
            0.0,
            None,
            elevation,
            None,
            "center-line",
        )
        return self._state.set_projection_data(
            best_point, best_dlong, 0.0, None, elevation, None, "center-line"
        )

    def _update_ai_line_projection(
        self, point: QtCore.QPointF | None, lp_name: str, size: QtCore.QSize
    ) -> bool:
        if point is None or lp_name not in self._model.visible_lp_files:
            return self._state.set_projection_data(
                None, None, None, None, None, None, None
            )

        records = self._model.ai_line_records(lp_name)
        if not records:
            return self._state.set_projection_data(
                None, None, None, None, None, None, None
            )

        if (
            self._state.projection_cached_point is not None
            and self._state.projection_cached_result is not None
            and (point - self._state.projection_cached_point).manhattanLength() <= 3
            and self._state.projection_cached_result[-1] == lp_name
        ):
            (
                cached_point,
                cached_dlong,
                cached_dlat,
                cached_speed,
                cached_elevation,
                cached_acceleration,
                cached_line,
            ) = self._state.projection_cached_result
            return self._state.set_projection_data(
                cached_point,
                cached_dlong,
                cached_dlat,
                cached_speed,
                cached_elevation,
                cached_acceleration,
                cached_line,
            )

        transform = self._state.current_transform(self._model.bounds, size)
        if not transform or not self._model.trk:
            return self._state.set_projection_data(
                None, None, None, None, None, None, None
            )

        cursor_track = self._state.map_to_track(point, self._model.bounds, size)
        if cursor_track is None:
            return self._state.set_projection_data(
                None, None, None, None, None, None, None
            )

        cursor_x, cursor_y = cursor_track
        best_point: tuple[float, float] | None = None
        best_distance_sq = math.inf
        best_dlong = None
        best_dlat = None
        best_speed = None
        best_accel = None

        track_length = float(self._model.trk.trklength) if self._model.trk else None
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
                dlong_delta = p1.dlong - p0.dlong
                if track_length is not None and dlong_delta < 0:
                    dlong_delta += track_length
                interp_dlong = p0.dlong + dlong_delta * t
                if track_length is not None and interp_dlong >= track_length:
                    interp_dlong -= track_length
                best_dlong = interp_dlong
                best_dlat = p0.dlat + (p1.dlat - p0.dlat) * t
                best_speed = p0.speed_mph + (p1.speed_mph - p0.speed_mph) * t
                best_accel = rendering.compute_segment_acceleration(
                    p0, p1, track_length=track_length
                )

        if best_point is None:
            return self._state.set_projection_data(
                None, None, None, None, None, None, None
            )

        mapped_point = rendering.map_point(
            best_point[0], best_point[1], transform, size.height()
        )
        pixel_distance = (mapped_point - point).manhattanLength()
        if pixel_distance > 16:
            self._state.projection_cached_point = point
            self._state.projection_cached_result = (
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            )
            return self._state.set_projection_data(
                None, None, None, None, None, None, None
            )

        self._state.projection_cached_point = point
        self._state.projection_cached_result = (
            best_point,
            best_dlong,
            best_dlat,
            best_speed,
            None,
            best_accel,
            lp_name,
        )
        return self._state.set_projection_data(
            best_point,
            best_dlong,
            best_dlat,
            best_speed,
            None,
            best_accel,
            lp_name,
        )

    def _handle_primary_click(self, point: QtCore.QPointF, size: QtCore.QSize) -> None:
        transform = self._state.current_transform(self._model.bounds, size)
        if not transform:
            return
        if self._state.camera_selection_enabled:
            camera_index = self._selection.camera_at_point(point, size)
            if camera_index is not None:
                if camera_index == self._state.selected_camera:
                    self._selection.emit_selected_camera()
                else:
                    self._selection.set_selected_camera(camera_index)
                return
        flag_index = self._selection.flag_at_point(point, size)
        if flag_index is not None:
            self._selection.set_selected_flag(flag_index)
            return
        active_line = self._state.active_lp_line or "center-line"
        if (
            active_line != "center-line"
            and active_line in self._model.visible_lp_files
            and self._model.surface_mesh
        ):
            if self._lp_edit.select_lp_record_at_point(point, active_line, size):
                return
        coords = self._state.map_to_track(point, self._model.bounds, size)
        if coords is None:
            return
        if not self._state.flag_drawing_enabled:
            return
        self._flag_edit.add_flag(coords)
