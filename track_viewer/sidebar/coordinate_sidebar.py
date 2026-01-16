"""Coordinate sidebar widget for camera and cursor metadata."""
from __future__ import annotations

from typing import Optional

from PyQt5 import QtCore, QtWidgets

from icr2_core.cam.helpers import CameraPosition
from track_viewer.model.camera_models import CameraViewListing
from track_viewer.sidebar.camera_table import CameraCoordinateTable
from track_viewer.sidebar.coordinate_sidebar_vm import CoordinateSidebarViewModel
from track_viewer.sidebar.tv_modes_panel import TvModesPanel
from track_viewer.sidebar.type6_editor import Type6Editor
from track_viewer.sidebar.type7_details import Type7Details


class CoordinateSidebar(QtWidgets.QFrame):
    """Utility sidebar that mirrors cursor and camera details."""

    cameraSelectionChanged = QtCore.pyqtSignal(object)
    cameraDlongsUpdated = QtCore.pyqtSignal(int, object, object)
    cameraPositionUpdated = QtCore.pyqtSignal(int, object, object, object)
    cameraAssignmentChanged = QtCore.pyqtSignal()
    type6ParametersChanged = QtCore.pyqtSignal()
    tvModeCountChanged = QtCore.pyqtSignal(int)
    tvModeViewChanged = QtCore.pyqtSignal(int)
    showCurrentTvOnlyChanged = QtCore.pyqtSignal(bool)
    zoomPointsToggled = QtCore.pyqtSignal(bool)
    addType6Requested = QtCore.pyqtSignal()
    addType2Requested = QtCore.pyqtSignal()
    addType7Requested = QtCore.pyqtSignal()

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
        self._current_tv_only_checkbox = QtWidgets.QCheckBox(
            "Show cameras for current TV mode only"
        )
        self._current_tv_only_checkbox.stateChanged.connect(
            self._handle_show_current_tv_only_changed
        )
        self._zoom_points_checkbox = QtWidgets.QCheckBox("Show Zoom Points")
        self._zoom_points_checkbox.stateChanged.connect(
            self._handle_zoom_points_changed
        )
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
        self._tv_panel.cameraAssignmentChanged.connect(self.cameraAssignmentChanged)
        self._tv_panel.modeCountChanged.connect(self.tvModeCountChanged)
        self._tv_panel.viewChanged.connect(self._handle_tv_mode_view_changed)
        self._tv_panel.addType6Requested.connect(self.addType6Requested)
        self._tv_panel.addType2Requested.connect(self.addType2Requested)
        self._tv_panel.addType7Requested.connect(self.addType7Requested)
        self._camera_table.positionUpdated.connect(self._handle_camera_position_updated)
        self._type6_editor.set_tv_dlongs_provider(self._tv_panel.camera_dlongs)
        self._type6_editor.parametersChanged.connect(self._handle_type6_parameters_changed)

        layout = QtWidgets.QVBoxLayout()
        layout.setSpacing(12)

        camera_title = QtWidgets.QLabel("Track cameras")
        camera_title.setStyleSheet("font-weight: bold")
        layout.addWidget(camera_title)
        layout.addWidget(self._camera_list)
        camera_filter_layout = QtWidgets.QHBoxLayout()
        camera_filter_layout.setContentsMargins(0, 0, 0, 0)
        camera_filter_layout.addWidget(self._current_tv_only_checkbox)
        camera_filter_layout.addWidget(self._zoom_points_checkbox)
        camera_filter_layout.addStretch(1)
        layout.addLayout(camera_filter_layout)

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
        self._apply_camera_list_state(list_state)

    def select_camera(self, index: int | None) -> None:
        self._camera_list.blockSignals(True)
        list_index = self._view_model.list_index_for_camera(index)
        self._camera_list.setCurrentIndex(list_index if list_index is not None else -1)
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
        list_index = self._view_model.list_index_for_camera(index)
        if self._camera_list.currentIndex() != (list_index if list_index is not None else -1):
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

    def _handle_tv_mode_view_changed(self, index: int) -> None:
        list_state = self._view_model.set_camera_filter(tv_mode_index=index)
        self._apply_camera_list_state(list_state)
        self.tvModeViewChanged.emit(index)

    def _handle_show_current_tv_only_changed(self, state: int) -> None:
        enabled = state == QtCore.Qt.Checked
        list_state = self._view_model.set_camera_filter(show_current_tv_only=enabled)
        self._apply_camera_list_state(list_state)
        self.showCurrentTvOnlyChanged.emit(enabled)

    def _handle_zoom_points_changed(self, state: int) -> None:
        self.zoomPointsToggled.emit(state == QtCore.Qt.Checked)

    def _apply_camera_list_state(self, list_state) -> None:
        self._camera_list.blockSignals(True)
        self._camera_list.clear()
        for label in list_state.labels:
            self._camera_list.addItem(label)
        self._camera_list.setEnabled(list_state.enabled)
        self._camera_details.setText(list_state.status_text)
        if list_state.selected_index is None:
            self._camera_list.setCurrentIndex(-1)
        else:
            self._camera_list.setCurrentIndex(list_state.selected_index)
        self._camera_list.blockSignals(False)

    def _create_readonly_field(self, placeholder: str) -> QtWidgets.QLineEdit:
        field = QtWidgets.QLineEdit()
        field.setReadOnly(True)
        field.setPlaceholderText(placeholder)
        field.setFocusPolicy(QtCore.Qt.ClickFocus)
        return field

    @staticmethod
    def _format_value(value: float) -> str:
        return f"{value:.2f}"
