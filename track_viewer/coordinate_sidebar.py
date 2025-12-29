"""UI sidebar that mirrors cursor, flag, and camera details."""
from __future__ import annotations

from typing import List, Optional

from PyQt5 import QtCore, QtWidgets

from icr2_core.cam.helpers import CameraPosition
from track_viewer.camera_models import CameraViewListing
from track_viewer.type6_editor import Type6Editor
from track_viewer.type7_details import Type7Details
from track_viewer.ui_loader import load_ui


class CoordinateSidebar(QtWidgets.QFrame):
    """Utility sidebar that mirrors cursor, flag and camera details."""

    cameraSelectionChanged = QtCore.pyqtSignal(object)
    cameraDlongsUpdated = QtCore.pyqtSignal(int, object, object)
    cameraPositionUpdated = QtCore.pyqtSignal(int, object, object, object)
    type6ParametersChanged = QtCore.pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        load_ui(self, "coordinate_sidebar.ui")

        self._track_length: int | None = None

        self._cursor_x = self.cursor_x
        self._cursor_y = self.cursor_y
        self._flag_x = self.flag_x
        self._flag_y = self.flag_y
        self._camera_list = self.camera_list
        self._tv_panel = self.tv_panel
        self._camera_table = self.camera_table
        self._camera_details = self.camera_details
        self._type6_editor: Optional[Type6Editor] = None
        self._type7_details: Optional[Type7Details] = None
        self._cameras: List[CameraPosition] = []
        self._selected_camera_index: int | None = None

        self._camera_list.currentRowChanged.connect(self._on_camera_selected)
        self._camera_details.setTextFormat(QtCore.Qt.RichText)
        self._camera_details.setWordWrap(True)
        self._camera_details.setAlignment(QtCore.Qt.AlignTop)

        self._tv_panel.cameraSelected.connect(self.cameraSelectionChanged)
        self._tv_panel.dlongsUpdated.connect(self.cameraDlongsUpdated)
        self._camera_table.positionUpdated.connect(self._handle_camera_position_updated)

    def attach_type_editors(
        self, type6_editor: Type6Editor, type7_details: Type7Details
    ) -> None:
        self._type6_editor = type6_editor
        self._type7_details = type7_details
        self._type6_editor.set_tv_dlongs_provider(self._tv_panel.camera_dlongs)
        self._type6_editor.parametersChanged.connect(
            self._handle_type6_parameters_changed
        )

    @property
    def type6_editor(self) -> Type6Editor:
        if self._type6_editor is None:
            raise RuntimeError("Type 6 editor has not been attached yet.")
        return self._type6_editor

    @property
    def type7_details(self) -> Type7Details:
        if self._type7_details is None:
            raise RuntimeError("Type 7 details widget has not been attached yet.")
        return self._type7_details

    def set_track_length(self, track_length: Optional[int]) -> None:
        self._track_length = track_length if track_length is not None else None
        self._tv_panel.set_track_length(self._track_length)
        if self._type6_editor is not None:
            self._type6_editor.set_track_length(self._track_length)

    def update_cursor_position(self, coords: Optional[tuple[float, float]]) -> None:
        if coords is None:
            self._cursor_x.clear()
            self._cursor_y.clear()
            return
        self._cursor_x.setText(self._format_value(coords[0]))
        self._cursor_y.setText(self._format_value(coords[1]))

    def update_flag_position(self, coords: Optional[tuple[float, float]]) -> None:
        if coords is None:
            self._flag_x.clear()
            self._flag_y.clear()
            return
        self._flag_x.setText(self._format_value(coords[0]))
        self._flag_y.setText(self._format_value(coords[1]))

    def set_cameras(
        self, cameras: List[CameraPosition], views: List[CameraViewListing]
    ) -> None:
        self._cameras = cameras
        self._camera_views = views
        self._selected_camera_index = None
        self._camera_table.set_camera(None, None)
        if self._type6_editor is not None:
            self._type6_editor.set_camera(None, None)
        if self._type7_details is not None:
            self._type7_details.set_camera(None, None)
        self._tv_panel.set_views(views, cameras)
        self._camera_list.blockSignals(True)
        self._camera_list.clear()
        if not cameras:
            self._camera_list.addItem("(No cameras found)")
            self._camera_list.setEnabled(False)
            self._camera_details.setText("This track does not define any camera positions.")
            self._camera_list.setCurrentRow(-1)
        else:
            for cam in cameras:
                label = f"#{cam.index} (type {cam.camera_type})"
                item = QtWidgets.QListWidgetItem(label)
                self._camera_list.addItem(item)
            self._camera_list.setEnabled(True)
            self._camera_details.setText("Select a camera to inspect.")
            self._camera_list.setCurrentRow(-1)
        self._camera_list.blockSignals(False)

    def select_camera(self, index: int | None) -> None:
        self._camera_list.blockSignals(True)
        if index is None:
            self._camera_list.setCurrentRow(-1)
        else:
            self._camera_list.setCurrentRow(index)
        self._camera_list.blockSignals(False)
        self._tv_panel.select_camera(index)
        if index is None:
            self._camera_table.setCurrentCell(-1, -1)
        elif self._camera_table.isEnabled():
            self._camera_table.setCurrentCell(0, 0)

    def update_selected_camera_details(
        self, index: int | None, camera: Optional[CameraPosition]
    ) -> None:
        if camera is None:
            self._camera_details.setText("Select a camera to inspect.")
            self._selected_camera_index = None
            self._camera_table.set_camera(None, None)
            if self._type6_editor is not None:
                self._type6_editor.set_camera(None, None)
            if self._type7_details is not None:
                self._type7_details.set_camera(None, None)
            if index is None:
                self.select_camera(None)
            return
        self._selected_camera_index = index
        self._camera_table.set_camera(index, camera)

        details = [f"Index: {camera.index}", f"Type: {camera.camera_type}"]

        if camera.camera_type == 6 and camera.type6 is not None:
            details.append("Type 6 parameters can be edited below.")
            if self._type6_editor is not None:
                self._type6_editor.set_camera(index, camera)
        elif self._type6_editor is not None:
            self._type6_editor.set_camera(None, None)

        if camera.camera_type == 7 and camera.type7 is not None:
            params = camera.type7
            details.append("Type 7 parameters:")
            details.append(
                "Z-axis rotation: {0}, vertical rotation: {1}, tilt: {2}, zoom: {3}".format(
                    params.z_axis_rotation,
                    params.vertical_rotation,
                    params.tilt,
                    params.zoom,
                )
            )
            details.append(
                "Unknowns: {0}, {1}, {2}, {3}".format(
                    params.unknown1,
                    params.unknown2,
                    params.unknown3,
                    params.unknown4,
                )
            )
            if self._type7_details is not None:
                self._type7_details.set_camera(index, camera)
        elif self._type7_details is not None:
            self._type7_details.set_camera(None, None)

        self._camera_details.setText("<br>".join(details))
        if index is not None and self._camera_list.currentRow() != index:
            self.select_camera(index)

    def _handle_camera_position_updated(
        self, index: int, x: Optional[int], y: Optional[int], z: Optional[int]
    ) -> None:
        if (
            self._selected_camera_index is not None
            and index == self._selected_camera_index
            and 0 <= index < len(self._cameras)
        ):
            self.update_selected_camera_details(index, self._cameras[index])
        self.cameraPositionUpdated.emit(index, x, y, z)

    def _handle_type6_parameters_changed(self) -> None:
        self.type6ParametersChanged.emit()

    def _on_camera_selected(self, index: int) -> None:
        if not self._cameras or index < 0 or index >= len(self._cameras):
            self.cameraSelectionChanged.emit(None)
            return
        self.cameraSelectionChanged.emit(index)

    @staticmethod
    def _format_value(value: float) -> str:
        return f"{value:.2f}"
