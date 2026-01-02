"""Coordinate sidebar widget for camera and cursor metadata."""
from __future__ import annotations

from typing import Optional

from PyQt5 import QtCore, QtWidgets

from icr2_core.cam.helpers import CameraPosition
from track_viewer.camera_models import CameraViewListing
from track_viewer.camera_table import CameraCoordinateTable
from track_viewer.coordinate_sidebar_vm import CoordinateSidebarViewModel
from track_viewer.tv_modes_panel import TvModesPanel
from track_viewer.type6_editor import Type6Editor
from track_viewer.type7_details import Type7Details


class CoordinateSidebar(QtWidgets.QFrame):
    """Utility sidebar that mirrors cursor and camera details."""

    cameraSelectionChanged = QtCore.pyqtSignal(object)
    cameraDlongsUpdated = QtCore.pyqtSignal(int, object, object)
    cameraPositionUpdated = QtCore.pyqtSignal(int, object, object, object)
    type6ParametersChanged = QtCore.pyqtSignal()
    tvModeCountChanged = QtCore.pyqtSignal(int)

    def __init__(self, view_model: CoordinateSidebarViewModel | None = None) -> None:
        super().__init__()
        self._view_model = view_model or CoordinateSidebarViewModel()
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setMinimumWidth(220)

        self._cursor_x = self._create_readonly_field("–")
        self._cursor_y = self._create_readonly_field("–")
        self._camera_list = QtWidgets.QComboBox()
        self._camera_list.setMinimumWidth(160)
        self._camera_list.currentIndexChanged.connect(self._on_camera_selected)
        self._tv_panel = TvModesPanel()
        self._camera_table = CameraCoordinateTable()
        self._camera_details = QtWidgets.QLabel("Select a camera to inspect.")
        self._camera_details.setTextFormat(QtCore.Qt.RichText)
        self._camera_details.setWordWrap(True)
        self._camera_details.setAlignment(QtCore.Qt.AlignTop)
        self._camera_details.setStyleSheet("font-size: 12px")
        self._type6_editor = Type6Editor()
        self._type7_details = Type7Details()

        self._tv_panel.cameraSelected.connect(self.cameraSelectionChanged)
        self._tv_panel.dlongsUpdated.connect(self.cameraDlongsUpdated)
        self._tv_panel.modeCountChanged.connect(self.tvModeCountChanged)
        self._camera_table.positionUpdated.connect(self._handle_camera_position_updated)
        self._type6_editor.set_tv_dlongs_provider(self._tv_panel.camera_dlongs)
        self._type6_editor.parametersChanged.connect(self._handle_type6_parameters_changed)

        layout = QtWidgets.QVBoxLayout()
        layout.setSpacing(12)

        camera_title = QtWidgets.QLabel("Track cameras")
        camera_title.setStyleSheet("font-weight: bold")
        layout.addWidget(camera_title)
        layout.addWidget(self._camera_list)

        layout.addWidget(self._tv_panel)

        coords_title = QtWidgets.QLabel("World coordinates")
        coords_title.setStyleSheet("font-weight: bold")
        layout.addWidget(coords_title)
        layout.addWidget(self._camera_table)

        layout.addStretch(1)
        self.setLayout(layout)

    @property
    def type6_editor(self) -> Type6Editor:
        return self._type6_editor

    @property
    def type7_details(self) -> Type7Details:
        return self._type7_details

    def set_tv_mode_count(self, count: int) -> None:
        self._tv_panel.set_mode_count(count)

    def set_track_length(self, track_length: Optional[int]) -> None:
        self._view_model.set_track_length(track_length)
        self._tv_panel.set_track_length(self._view_model.track_length)
        self._type6_editor.set_track_length(self._view_model.track_length)

    def update_cursor_position(self, coords: Optional[tuple[float, float]]) -> None:
        if coords is None:
            self._cursor_x.clear()
            self._cursor_y.clear()
            return
        self._cursor_x.setText(self._format_value(coords[0]))
        self._cursor_y.setText(self._format_value(coords[1]))

    def set_cameras(
        self, cameras: list[CameraPosition], views: list[CameraViewListing]
    ) -> None:
        list_state = self._view_model.set_cameras(cameras, views)
        self._camera_table.set_camera(None, None)
        self._type6_editor.set_camera(None, None)
        self._type7_details.set_camera(None, None)
        self._tv_panel.set_views(views, cameras)
        self._camera_list.blockSignals(True)
        self._camera_list.clear()
        for label in list_state.labels:
            self._camera_list.addItem(label)
        self._camera_list.setEnabled(list_state.enabled)
        self._camera_details.setText(list_state.status_text)
        self._camera_list.setCurrentIndex(-1)
        self._camera_list.blockSignals(False)

    def select_camera(self, index: int | None) -> None:
        self._camera_list.blockSignals(True)
        if index is None:
            self._camera_list.setCurrentIndex(-1)
        else:
            self._camera_list.setCurrentIndex(index)
        self._camera_list.blockSignals(False)
        self._tv_panel.select_camera(index)
        if index is None:
            self._camera_table.setCurrentCell(-1, -1)
        elif self._camera_table.isEnabled():
            self._camera_table.setCurrentCell(0, 0)

    def update_selected_camera_details(
        self, index: int | None, camera: CameraPosition | None
    ) -> None:
        state = self._view_model.update_selected_camera_details(index, camera)
        self._camera_details.setText(state.details_html)
        if camera is None:
            self._camera_table.set_camera(None, None)
            self._type6_editor.set_camera(None, None)
            self._type7_details.set_camera(None, None)
            if index is None:
                self.select_camera(None)
            return
        self._camera_table.set_camera(state.selected_index, camera)
        self._type6_editor.set_camera(state.selected_index, state.type6_camera)
        self._type7_details.set_camera(state.selected_index, state.type7_camera)
        if index is not None and self._camera_list.currentIndex() != index:
            self.select_camera(index)

    def _handle_camera_position_updated(
        self, index: int, x: Optional[int], y: Optional[int], z: Optional[int]
    ) -> None:
        camera = self._view_model.camera_needing_refresh(index)
        if camera is not None:
            self.update_selected_camera_details(index, camera)
        self.cameraPositionUpdated.emit(index, x, y, z)

    def _handle_type6_parameters_changed(self) -> None:
        self.type6ParametersChanged.emit()

    def _on_camera_selected(self, index: int) -> None:
        resolved = self._view_model.resolve_camera_selection(index)
        if resolved is None:
            self.cameraSelectionChanged.emit(None)
            return
        self.cameraSelectionChanged.emit(resolved)

    def _create_readonly_field(self, placeholder: str) -> QtWidgets.QLineEdit:
        field = QtWidgets.QLineEdit()
        field.setReadOnly(True)
        field.setPlaceholderText(placeholder)
        field.setFocusPolicy(QtCore.Qt.ClickFocus)
        return field

    @staticmethod
    def _format_value(value: float) -> str:
        return f"{value:.2f}"
