"""Embedded surface preview widget for the standalone track viewer."""
from __future__ import annotations

import math
from pathlib import Path
from typing import List, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.cam.helpers import CameraPosition
from icr2_core.trk.trk_utils import get_cline_pos, getxyz, sect2xy
from track_viewer.ai_line_service import LpPoint
from track_viewer.camera_controller import CameraController
from track_viewer.camera_service import CameraService
from track_viewer.interaction import InteractionCallbacks, TrackPreviewInteraction
from track_viewer.io_service import TrackIOService
from track_viewer.pit_models import PitParameters
from track_viewer.preview_constants import LP_COLORS, LP_FILE_NAMES
from track_viewer.renderer import TrackPreviewRenderer
from track_viewer.track_preview_model import TrackPreviewModel
from track_viewer.view_state import TrackPreviewViewState


class TrackPreviewWidget(QtWidgets.QFrame):
    """Renders the TRK ground surface similar to the timing overlay."""

    cursorPositionChanged = QtCore.pyqtSignal(object)
    selectedFlagChanged = QtCore.pyqtSignal(object)
    camerasChanged = QtCore.pyqtSignal(list, list)
    selectedCameraChanged = QtCore.pyqtSignal(object, object)
    activeLpLineChanged = QtCore.pyqtSignal(str)
    aiLineLoaded = QtCore.pyqtSignal(str)
    lpRecordSelected = QtCore.pyqtSignal(str, int)
    diagramClicked = QtCore.pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(320, 240)
        self.setAutoFillBackground(True)
        self.setMouseTracking(True)

        palette = self.palette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor(24, 24, 24))
        self.setPalette(palette)

        self._state = TrackPreviewViewState()

        self._io_service = TrackIOService()
        self._model = TrackPreviewModel(self._io_service)
        self._model.aiLineLoaded.connect(self._handle_model_ai_line_loaded)
        self._camera_service = CameraService(self._io_service, CameraController())
        self._renderer = TrackPreviewRenderer(self._model, self._camera_service, self._state)
        self._interaction = TrackPreviewInteraction(
            self._model,
            self._camera_service,
            self._state,
            InteractionCallbacks(
                update=self.update,
                cursor_position_changed=self.cursorPositionChanged.emit,
                selected_flag_changed=self.selectedFlagChanged.emit,
                selected_camera_changed=self.selectedCameraChanged.emit,
                lp_record_selected=self._emit_lp_record_selected,
                diagram_clicked=self.diagramClicked.emit,
            ),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def clear(self, message: str = "Select a track to preview.") -> None:
        self._model.clear()
        self._state.reset(message)
        self._camera_service.reset()
        self.cursorPositionChanged.emit(None)
        self.selectedFlagChanged.emit(None)
        self.camerasChanged.emit([], [])
        self.selectedCameraChanged.emit(None, None)
        self.update()

    def tv_mode_count(self) -> int:
        return self._camera_service.tv_mode_count

    def set_tv_mode_count(self, count: int) -> None:
        updated_count = self._camera_service.set_tv_mode_count(count)
        if not updated_count:
            return
        self.camerasChanged.emit(
            self._camera_service.cameras, self._camera_service.camera_views
        )
        self.update()

    # ------------------------------------------------------------------
    # Center line controls
    # ------------------------------------------------------------------
    def set_show_center_line(self, show: bool) -> None:
        """Enable or disable rendering of the track center line."""

        if self._state.show_center_line != show:
            self._state.show_center_line = show
            if not show and self._state.active_lp_line == "center-line":
                if self._state.set_projection_data(
                    None, None, None, None, None, None, None
                ):
                    self.update()
            self.update()

    def set_show_boundaries(self, show: bool) -> None:
        """Enable or disable rendering of the track boundary edges."""

        if self._state.show_boundaries != show:
            self._state.show_boundaries = show
            self.update()

    def set_show_section_dividers(self, show: bool) -> None:
        """Enable or disable rendering of TRK section divider lines."""

        if self._state.show_section_dividers != show:
            self._state.show_section_dividers = show
            self.update()

    def center_line_visible(self) -> bool:
        return self._state.show_center_line

    def ai_line_available(self) -> bool:
        return self._model.ai_line_available()

    def available_lp_files(self) -> list[str]:
        return list(self._model.available_lp_files)

    def ai_acceleration_window(self) -> int:
        return self._state.ai_acceleration_window

    def set_ai_acceleration_window(self, segments: int) -> None:
        clamped = max(1, segments)
        if self._state.ai_acceleration_window != clamped:
            self._state.ai_acceleration_window = clamped
            self.update()

    def ai_line_width(self) -> int:
        return self._state.ai_line_width

    def set_ai_line_width(self, width: int) -> None:
        clamped = max(1, width)
        if self._state.ai_line_width != clamped:
            self._state.ai_line_width = clamped
            self.update()

    def flag_radius(self) -> float:
        return self._state.flag_radius

    def set_flag_radius(self, radius: float) -> None:
        clamped = max(0.0, radius)
        if self._state.flag_radius != clamped:
            self._state.flag_radius = clamped
            self.update()

    def set_radius_raw_visible(self, enabled: bool) -> None:
        if self._state.show_radius_raw == enabled:
            return
        self._state.show_radius_raw = enabled
        self.update()

    def _handle_model_ai_line_loaded(self, lp_name: str) -> None:
        self.aiLineLoaded.emit(lp_name)
        self.update()

    def visible_lp_files(self) -> list[str]:
        return sorted(self._model.visible_lp_files)

    def set_visible_lp_files(self, names: list[str] | set[str]) -> None:
        if not self._model.set_visible_lp_files(names):
            return
        self.update()

    def active_lp_line(self) -> str:
        return self._state.active_lp_line

    def set_active_lp_line(self, name: str) -> None:
        target = "center-line"
        if name in self._model.available_lp_files:
            target = name
        elif name == "center-line":
            target = name
        if target == self._state.active_lp_line:
            return
        self._state.active_lp_line = target
        self._state.selected_lp_line = None
        self._state.selected_lp_index = None
        self._state.projection_cached_point = None
        self._state.projection_cached_result = None
        self._state.set_projection_data(None, None, None, None, None, None, None)
        self.activeLpLineChanged.emit(target)
        if target != "center-line":
            self._model.ai_line_records(target)
        self.update()

    def ai_line_records(self, name: str) -> list[LpPoint]:
        return self._model.ai_line_records(name)

    def update_lp_record(self, lp_name: str, index: int) -> None:
        if not self._model.update_lp_record(lp_name, index):
            return
        self._state.projection_cached_point = None
        self._state.projection_cached_result = None
        self.update()

    def save_active_lp_line(self) -> tuple[bool, str]:
        return self._model.save_lp_line(self._state.active_lp_line)

    def export_active_lp_csv(self, output_path: Path) -> tuple[bool, str]:
        return self._model.export_lp_csv(self._state.active_lp_line, output_path)

    def set_selected_lp_record(self, name: str | None, index: int | None) -> None:
        if name is None or index is None:
            if self._state.selected_lp_line is None and self._state.selected_lp_index is None:
                return
            self._state.selected_lp_line = None
            self._state.selected_lp_index = None
            self.update()
            return
        if name not in self._model.available_lp_files:
            return
        records = self._model.ai_line_records(name)
        if index < 0 or index >= len(records):
            return
        if self._state.selected_lp_line == name and self._state.selected_lp_index == index:
            return
        self._state.selected_lp_line = name
        self._state.selected_lp_index = index
        self.update()

    def set_lp_shortcut_active(self, active: bool) -> None:
        if self._state.lp_shortcut_active == active:
            return
        self._state.lp_shortcut_active = active
        self.update()

    def set_lp_dlat_step(self, step: int) -> None:
        clamped = max(0, int(step))
        if self._state.lp_dlat_step == clamped:
            return
        self._state.lp_dlat_step = clamped
        if self._state.lp_shortcut_active:
            self.update()

    def lp_color(self, name: str) -> str:
        try:
            index = LP_FILE_NAMES.index(name)
        except ValueError:
            return "#e53935"
        return LP_COLORS[index % len(LP_COLORS)]

    def set_show_zoom_points(self, show: bool) -> None:
        """Enable or disable rendering of zoom DLONG markers."""

        if self._state.show_zoom_points != show:
            self._state.show_zoom_points = show
            self.update()

    def set_ai_speed_gradient_enabled(self, enabled: bool) -> None:
        """Toggle AI line rendering between solid colors and speed gradient."""

        self.set_ai_color_mode("speed" if enabled else "none")

    def set_ai_acceleration_gradient_enabled(self, enabled: bool) -> None:
        """Toggle AI line rendering between solid colors and acceleration gradient."""

        self.set_ai_color_mode("acceleration" if enabled else "none")

    def set_ai_color_mode(self, mode: str) -> None:
        if mode not in {"none", "speed", "acceleration"}:
            mode = "none"
        if self._state.ai_color_mode != mode:
            self._state.ai_color_mode = mode
            self.update()

    def track_length(self) -> Optional[int]:
        return int(self._model.track_length) if self._model.track_length is not None else None

    @property
    def trk(self) -> object | None:
        return self._model.trk

    def set_show_cameras(self, show: bool) -> None:
        """Enable or disable rendering of track camera overlays."""

        if self._state.show_cameras != show:
            self._state.show_cameras = show
            self.update()

    def set_pit_parameters(self, params: PitParameters | None) -> None:
        if params == self._state.pit_params:
            return
        self._state.pit_params = params
        self.update()

    def set_visible_pit_indices(self, indices: set[int]) -> None:
        if indices == self._state.visible_pit_indices:
            return
        self._state.visible_pit_indices = set(indices)
        self.update()

    def cameras(self) -> List[CameraPosition]:
        return list(self._camera_service.cameras)

    def update_camera_dlongs(
        self, camera_index: int, start_dlong: Optional[int], end_dlong: Optional[int]
    ) -> None:
        if camera_index < 0 or camera_index >= len(self._camera_service.cameras):
            return

        if self._state.selected_camera == camera_index:
            self._emit_selected_camera()
        self.update()

    def update_camera_position(
        self, camera_index: int, x: Optional[int], y: Optional[int], z: Optional[int]
    ) -> None:
        if camera_index < 0 or camera_index >= len(self._camera_service.cameras):
            return
        camera = self._camera_service.cameras[camera_index]
        if x is not None:
            camera.x = int(x)
        if y is not None:
            camera.y = int(y)
        if z is not None:
            camera.z = int(z)
        if self._state.selected_camera == camera_index:
            self._emit_selected_camera()
        self.update()

    def set_selected_camera(self, index: int | None) -> None:
        if index == self._state.selected_camera:
            return
        if index is not None:
            if index < 0 or index >= len(self._camera_service.cameras):
                index = None
        self._state.selected_camera = index
        self._emit_selected_camera()
        self.update()

    def add_type6_camera(self) -> tuple[bool, str]:
        """Create a new type 6 camera relative to the current selection."""
        success, message, selected = self._camera_service.add_type6_camera(
            self._state.selected_camera, self._model.track_length
        )
        if success and selected is not None:
            self.set_selected_camera(selected)
        self.camerasChanged.emit(
            self._camera_service.cameras, self._camera_service.camera_views
        )
        self._state.status_message = message
        self.update()
        return success, message

    def add_type7_camera(self) -> tuple[bool, str]:
        """Create a new type 7 camera relative to the current selection."""
        success, message, selected = self._camera_service.add_type7_camera(
            self._state.selected_camera, self._model.track_length
        )
        if success and selected is not None:
            self.set_selected_camera(selected)
        self.camerasChanged.emit(
            self._camera_service.cameras, self._camera_service.camera_views
        )
        self._state.status_message = message
        self.update()
        return success, message

    def load_track(self, track_folder: Path) -> None:
        """Load and render the contents of a track folder."""
        if not track_folder:
            self.clear()
            return

        if self._model.track_path == track_folder:
            return  # nothing to do

        self._state.status_message = f"Loading {track_folder.name}…"
        self.update()

        try:
            self._model.load_track(track_folder)
        except Exception as exc:  # pragma: no cover - interactive feedback
            self.clear(f"Failed to load track: {exc}")
            return

        self._state.projection_cached_point = None
        self._state.projection_cached_result = None
        if self._state.active_lp_line not in {"center-line", *self._model.available_lp_files}:
            self._state.active_lp_line = "center-line"
        self._state.set_projection_data(None, None, None, None, None, None, None)
        self._state.cached_surface_pixmap = None
        self._state.pixmap_size = None
        self._state.status_message = f"Loaded {track_folder.name}" if track_folder else ""
        self._state.view_center = self._state.default_center(self._model.bounds)
        self._state.user_transform_active = False
        self._state.update_fit_scale(self._model.bounds, self.size())
        self._state.flags = []
        self._set_selected_flag(None)
        self._camera_service.load_for_track(track_folder)
        self.camerasChanged.emit(
            self._camera_service.cameras, self._camera_service.camera_views
        )
        self.set_selected_camera(None)
        self.update()

    def save_cameras(self) -> tuple[bool, str]:
        """Persist the current camera data back to disk."""

        if self._model.track_path is None:
            return False, "No track is currently loaded."

        try:
            self._state.status_message = self._camera_service.save()
            self.update()
        except Exception as exc:  # pragma: no cover - interactive feedback
            return False, f"Failed to save cameras: {exc}"

        return True, "Camera files saved successfully."

    def run_trk_gaps(self) -> tuple[bool, str]:
        """Replicate the ``trk_gaps`` script for the currently loaded track."""

        if self._model.trk is None or self._model.track_path is None:
            return False, "No track is currently loaded."

        track_name = self._model.track_path.name
        trk_path = self._model.track_path / f"{track_name}.trk"
        header_label = str(trk_path if trk_path.exists() else trk_path.name)

        try:
            cline = get_cline_pos(self._model.trk)
            dist_list: list[float] = []
            lines = [header_label]

            for sect in range(-1, self._model.trk.num_sects - 1):
                xy2 = getxyz(
                    self._model.trk,
                    self._model.trk.sects[sect].start_dlong
                    + self._model.trk.sects[sect].length
                    - 1,
                    0,
                    cline,
                )
                xy1 = sect2xy(self._model.trk, sect + 1, cline)

                dist = math.dist((xy1[0], xy1[1]), (xy2[0], xy2[1]))

                dist_list.append(dist)
                lines.append(f"Sect {sect}/{sect + 1}, gap {dist:.1f}")

            if dist_list:
                lines.append(f"Max gap {max(dist_list):.1f}")
                lines.append(f"Min gap {min(dist_list):.1f}")
                lines.append(f"Sum gaps {sum(dist_list):.1f}")
            lines.append(f"Track length: {self._model.trk.trklength}")
        except Exception as exc:  # pragma: no cover - interactive feedback
            return False, f"Failed to compute TRK gaps: {exc}"

        return True, "\n".join(lines)

    # ------------------------------------------------------------------
    # Qt events
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: D401 - Qt signature
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), self.palette().color(QtGui.QPalette.Window))
        self._renderer.paint(painter, self.size())

    def resizeEvent(self, event) -> None:  # noqa: D401 - Qt signature
        self._interaction.handle_resize(self.size())
        super().resizeEvent(event)

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:  # noqa: D401 - Qt signature
        if self._interaction.handle_wheel(event, self.size()):
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401 - Qt signature
        if self._interaction.handle_mouse_press(event, self.size()):
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401 - Qt signature
        handled = self._interaction.handle_mouse_move(event, self.size())
        if handled:
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401 - Qt signature
        if self._interaction.handle_mouse_release(event, self.size()):
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: D401 - Qt signature
        self._interaction.handle_leave()
        super().leaveEvent(event)

    # ------------------------------------------------------------------
    # Helper emitters
    # ------------------------------------------------------------------
    def _emit_selected_camera(self) -> None:
        selected = None
        index = self._state.selected_camera
        if index is not None and 0 <= index < len(self._camera_service.cameras):
            selected = self._camera_service.cameras[index]
        self.selectedCameraChanged.emit(index, selected)

    def _emit_lp_record_selected(self, name: str, index: int) -> None:
        self.lpRecordSelected.emit(name, index)

    def _set_selected_flag(self, index: int | None) -> None:
        self._state.selected_flag = index
        coords = None
        if index is not None and 0 <= index < len(self._state.flags):
            coords = self._state.flags[index]
        self.selectedFlagChanged.emit(coords)
        self.update()
