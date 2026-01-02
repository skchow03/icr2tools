"""Input interaction handlers for the track preview widget."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Tuple

from PyQt5 import QtCore, QtGui

from icr2_core.cam.helpers import CameraPosition
from icr2_core.trk.trk_utils import getxyz
from track_viewer import rendering
from track_viewer.geometry import project_point_to_centerline
from track_viewer.track_preview_model import TrackPreviewModel
from track_viewer.view_state import TrackPreviewViewState


@dataclass
class InteractionCallbacks:
    update: Callable[[], None]
    cursor_position_changed: Callable[[tuple[float, float] | None], None]
    selected_flag_changed: Callable[[tuple[float, float] | None], None]
    selected_camera_changed: Callable[[int | None, CameraPosition | None], None]
    lp_record_selected: Callable[[str, int], None]
    diagram_clicked: Callable[[], None]


class TrackPreviewInteraction:
    """Encapsulates mouse/keyboard logic and hit testing."""

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

    def handle_resize(self, size: QtCore.QSize) -> None:
        self._state.pixmap_size = None
        self._state.cached_surface_pixmap = None
        self._state.update_fit_scale(self._model.bounds, size)

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
        self._state.invalidate_cache()
        self._callbacks.update()
        return True

    def handle_mouse_press(self, event: QtGui.QMouseEvent, size: QtCore.QSize) -> bool:
        if event.button() == QtCore.Qt.RightButton and self._model.surface_mesh:
            if self._handle_flag_removal(event.pos(), size):
                return True

        if event.button() == QtCore.Qt.LeftButton:
            self._callbacks.diagram_clicked()
            if self._model.surface_mesh and self._handle_camera_press(
                event.pos(), size
            ):
                return True
            if self._model.surface_mesh and self._handle_flag_press(event.pos(), size):
                return True
            self._state.is_panning = True
            self._state.last_mouse_pos = event.pos()
            self._state.left_press_pos = event.pos()
            self._state.dragged_during_press = False
            self._state.user_transform_active = True
            return True
        return False

    def handle_mouse_move(self, event: QtGui.QMouseEvent, size: QtCore.QSize) -> bool:
        handled = False
        if self._state.dragging_camera_index is not None:
            self._update_camera_position(event.pos(), size)
            handled = True
        if self._state.dragging_flag_index is not None:
            self._update_flag_position(event.pos(), size)
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
                    self._state.invalidate_cache()
                    self._callbacks.update()
            handled = True
        self._update_cursor_position(event.pos(), size)
        return handled

    def handle_mouse_release(
        self, event: QtGui.QMouseEvent, size: QtCore.QSize
    ) -> bool:
        if event.button() == QtCore.Qt.LeftButton:
            if self._state.dragging_camera_index is not None:
                self._state.dragging_camera_index = None
                self._state.camera_dragged = False
                return True
            if self._state.dragging_flag_index is not None:
                self._state.dragging_flag_index = None
                return True
            click_without_drag = not self._state.dragged_during_press
            self._state.is_panning = False
            self._state.last_mouse_pos = None
            self._state.left_press_pos = None
            self._state.dragged_during_press = False
            if click_without_drag and self._model.surface_mesh:
                self._handle_primary_click(event.pos(), size)
            return True
        return False

    def handle_leave(self) -> None:
        self._callbacks.cursor_position_changed(None)
        if self._state.cursor_position is not None:
            self._state.cursor_position = None
            self._callbacks.update()
        if self._state.set_projection_data(None, None, None, None, None, None, None):
            self._callbacks.update()

    def _update_cursor_position(self, point: QtCore.QPointF, size: QtCore.QSize) -> None:
        if not self._model.surface_mesh or not self._model.bounds:
            self._callbacks.cursor_position_changed(None)
            if self._state.cursor_position is not None:
                self._state.cursor_position = None
                self._callbacks.update()
            if self._state.set_projection_data(None, None, None, None, None, None, None):
                self._callbacks.update()
            return
        coords = self._state.map_to_track(point, self._model.bounds, size)
        if self._state.set_cursor_position(coords):
            self._callbacks.update()
        self._callbacks.cursor_position_changed(coords)
        self._update_active_line_projection(point, size)

    def _update_active_line_projection(
        self, point: QtCore.QPointF | None, size: QtCore.QSize
    ) -> None:
        active = self._state.active_lp_line if self._state.active_lp_line else "center-line"
        if active != "center-line" and active not in self._model.available_lp_files:
            active = "center-line"
        if active == "center-line":
            self._update_centerline_projection(point, size)
            return
        self._update_ai_line_projection(point, active, size)

    def _update_centerline_projection(
        self, point: QtCore.QPointF | None, size: QtCore.QSize
    ) -> None:
        if (
            point is None
            or not self._model.sampled_centerline
            or not self._model.sampled_dlongs
            or not self._state.show_center_line
        ):
            if self._state.set_projection_data(None, None, None, None, None, None, None):
                self._callbacks.update()
            return

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
            if self._state.set_projection_data(
                cached_point,
                cached_dlong,
                cached_dlat,
                cached_speed,
                cached_elevation,
                cached_acceleration,
                cached_line,
            ):
                self._callbacks.update()
            return

        transform = self._state.current_transform(self._model.bounds, size)
        if not transform or not self._model.trk:
            if self._state.set_projection_data(None, None, None, None, None, None, None):
                self._callbacks.update()
            return

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
                if self._state.set_projection_data(
                    None, None, None, None, None, None, None
                ):
                    self._callbacks.update()
                return

        cursor_track = self._state.map_to_track(point, self._model.bounds, size)
        if cursor_track is None:
            if self._state.set_projection_data(None, None, None, None, None, None, None):
                self._callbacks.update()
            return

        if self._model.centerline_index is None:
            if self._state.set_projection_data(None, None, None, None, None, None, None):
                self._callbacks.update()
            return

        cursor_x, cursor_y = cursor_track
        track_length = float(self._model.trk.trklength)
        best_point, best_dlong, _ = project_point_to_centerline(
            (cursor_x, cursor_y),
            self._model.centerline_index,
            self._model.sampled_dlongs,
            track_length,
        )

        if best_point is None:
            if self._state.set_projection_data(None, None, None, None, None, None, None):
                self._callbacks.update()
            return
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
            if self._state.set_projection_data(None, None, None, None, None, None, None):
                self._callbacks.update()
            return
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
        if self._state.set_projection_data(
            best_point, best_dlong, 0.0, None, elevation, None, "center-line"
        ):
            self._callbacks.update()

    def _update_ai_line_projection(
        self, point: QtCore.QPointF | None, lp_name: str, size: QtCore.QSize
    ) -> None:
        if point is None or lp_name not in self._model.visible_lp_files:
            if self._state.set_projection_data(None, None, None, None, None, None, None):
                self._callbacks.update()
            return

        records = self._model.ai_line_records(lp_name)
        if not records:
            if self._state.set_projection_data(None, None, None, None, None, None, None):
                self._callbacks.update()
            return

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
            if self._state.set_projection_data(
                cached_point,
                cached_dlong,
                cached_dlat,
                cached_speed,
                cached_elevation,
                cached_acceleration,
                cached_line,
            ):
                self._callbacks.update()
            return

        transform = self._state.current_transform(self._model.bounds, size)
        if not transform or not self._model.trk:
            if self._state.set_projection_data(None, None, None, None, None, None, None):
                self._callbacks.update()
            return

        cursor_track = self._state.map_to_track(point, self._model.bounds, size)
        if cursor_track is None:
            if self._state.set_projection_data(None, None, None, None, None, None, None):
                self._callbacks.update()
            return

        cursor_x, cursor_y = cursor_track
        best_point: Tuple[float, float] | None = None
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
            if self._state.set_projection_data(None, None, None, None, None, None, None):
                self._callbacks.update()
            return

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
            if self._state.set_projection_data(None, None, None, None, None, None, None):
                self._callbacks.update()
            return

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
        if self._state.set_projection_data(
            best_point,
            best_dlong,
            best_dlat,
            best_speed,
            None,
            best_accel,
            lp_name,
        ):
            self._callbacks.update()

    def _camera_at_point(self, point: QtCore.QPointF, size: QtCore.QSize) -> int | None:
        transform = self._state.current_transform(self._model.bounds, size)
        if not transform:
            return None
        for index, cam in enumerate(self._camera_service.cameras):
            camera_point = rendering.map_point(cam.x, cam.y, transform, size.height())
            if (camera_point - point).manhattanLength() <= 10:
                return index
        return None

    def _handle_camera_press(self, point: QtCore.QPointF, size: QtCore.QSize) -> bool:
        camera_index = self._camera_at_point(point, size)
        if camera_index is None:
            return False
        self._state.selected_camera = camera_index
        self._emit_selected_camera()
        self._state.dragging_camera_index = camera_index
        self._state.camera_dragged = False
        self._state.is_panning = False
        self._state.dragged_during_press = False
        self._callbacks.update()
        return True

    def _handle_flag_press(self, point: QtCore.QPointF, size: QtCore.QSize) -> bool:
        flag_index = self._flag_at_point(point, size)
        if flag_index is None:
            return False
        self._set_selected_flag(flag_index)
        self._state.dragging_flag_index = flag_index
        self._state.is_panning = False
        self._state.dragged_during_press = False
        return True

    def _update_camera_position(self, point: QtCore.QPointF, size: QtCore.QSize) -> None:
        if self._state.dragging_camera_index is None:
            return
        coords = self._state.map_to_track(point, self._model.bounds, size)
        if coords is None:
            return
        index = self._state.dragging_camera_index
        if index < 0 or index >= len(self._camera_service.cameras):
            return
        cam = self._camera_service.cameras[index]
        cam.x = int(round(coords[0]))
        cam.y = int(round(coords[1]))
        self._state.camera_dragged = True
        self._emit_selected_camera()
        self._callbacks.update()

    def _update_flag_position(self, point: QtCore.QPointF, size: QtCore.QSize) -> None:
        if self._state.dragging_flag_index is None:
            return
        coords = self._state.map_to_track(point, self._model.bounds, size)
        if coords is None:
            return
        index = self._state.dragging_flag_index
        if index < 0 or index >= len(self._state.flags):
            return
        self._state.flags[index] = coords
        self._callbacks.selected_flag_changed(coords)
        self._callbacks.update()

    def _flag_at_point(self, point: QtCore.QPointF, size: QtCore.QSize) -> int | None:
        transform = self._state.current_transform(self._model.bounds, size)
        if not transform:
            return None
        for index, (fx, fy) in enumerate(self._state.flags):
            flag_point = rendering.map_point(fx, fy, transform, size.height())
            if (flag_point - point).manhattanLength() <= 8:
                return index
        return None

    def _handle_primary_click(self, point: QtCore.QPointF, size: QtCore.QSize) -> None:
        transform = self._state.current_transform(self._model.bounds, size)
        if not transform:
            return
        camera_index = self._camera_at_point(point, size)
        if camera_index is not None:
            self._state.selected_camera = camera_index
            self._emit_selected_camera()
            self._callbacks.update()
            return
        flag_index = self._flag_at_point(point, size)
        if flag_index is not None:
            self._set_selected_flag(flag_index)
            return
        active_line = self._state.active_lp_line or "center-line"
        if (
            active_line != "center-line"
            and active_line in self._model.visible_lp_files
            and self._model.surface_mesh
        ):
            lp_index = self._lp_record_at_point(point, active_line, size)
            if lp_index is not None:
                self._state.selected_lp_line = active_line
                self._state.selected_lp_index = lp_index
                self._callbacks.lp_record_selected(active_line, lp_index)
                self._callbacks.update()
                return
        coords = self._state.map_to_track(point, self._model.bounds, size)
        if coords is None:
            return
        self._state.flags.append(coords)
        self._set_selected_flag(len(self._state.flags) - 1)
        self._callbacks.update()

    def _lp_record_at_point(
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

    def _handle_flag_removal(self, point: QtCore.QPointF, size: QtCore.QSize) -> bool:
        flag_index = self._flag_at_point(point, size)
        if flag_index is None:
            return False
        del self._state.flags[flag_index]
        if self._state.selected_flag is not None:
            if self._state.selected_flag == flag_index:
                self._set_selected_flag(None)
            elif self._state.selected_flag > flag_index:
                self._set_selected_flag(self._state.selected_flag - 1)
        self._callbacks.update()
        return True

    def _set_selected_flag(self, index: int | None) -> None:
        self._state.selected_flag = index
        coords = None
        if index is not None and 0 <= index < len(self._state.flags):
            coords = self._state.flags[index]
        self._callbacks.selected_flag_changed(coords)
        self._callbacks.update()

    def _emit_selected_camera(self) -> None:
        selected = None
        index = self._state.selected_camera
        if index is not None and 0 <= index < len(self._camera_service.cameras):
            selected = self._camera_service.cameras[index]
        self._callbacks.selected_camera_changed(index, selected)
