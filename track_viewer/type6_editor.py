"""Type 6 parameter editor widget."""
from __future__ import annotations

from typing import Callable, Optional, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.cam.helpers import CameraPosition, Type6CameraParameters


class Type6Editor(QtWidgets.QGroupBox):
    """Displays and edits Type 6 camera parameters."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__("Type 6 parameters", parent)
        self._track_length: Optional[int] = None
        self._camera_index: Optional[int] = None
        self._camera: Optional[CameraPosition] = None
        self._tv_dlongs_provider: Callable[[int], Tuple[Optional[int], Optional[int]]]
        self._tv_dlongs_provider = lambda _index: (None, None)

        self._table = self._create_table()
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self._table)
        self.setLayout(layout)
        self.setVisible(False)

    def set_track_length(self, length: Optional[int]) -> None:
        self._track_length = length

    def set_tv_dlongs_provider(
        self, provider: Callable[[int], Tuple[Optional[int], Optional[int]]]
    ) -> None:
        self._tv_dlongs_provider = provider

    def set_camera(self, index: Optional[int], camera: Optional[CameraPosition]) -> None:
        self._camera_index = index
        self._camera = camera
        if camera is None or camera.type6 is None or index is None:
            self.setVisible(False)
            with QtCore.QSignalBlocker(self._table):
                for row in range(3):
                    for column in range(2):
                        self._table.item(row, column).setText("")
            return

        self._populate(camera.type6)
        self.setVisible(True)

    def _create_table(self) -> QtWidgets.QTableWidget:
        table = QtWidgets.QTableWidget(3, 3)
        table.setHorizontalHeaderLabels(["DLONG", "Zoom factor", "Actions"])
        table.setVerticalHeaderLabels(["Start", "Middle", "End"])
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        table.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked
            | QtWidgets.QAbstractItemView.SelectedClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed
        )
        table.setItemDelegate(_Type6ItemDelegate(self))
        table.itemChanged.connect(self._handle_item_changed)
        for row in range(3):
            for column in range(2):
                item = QtWidgets.QTableWidgetItem()
                item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)
                table.setItem(row, column, item)
        start_button = QtWidgets.QPushButton("Use TV Start")
        start_button.clicked.connect(lambda: self._apply_tv_dlong_to_row(0))
        table.setCellWidget(0, 2, start_button)

        average_button = QtWidgets.QPushButton("Average")
        average_button.clicked.connect(self._apply_middle_average)
        table.setCellWidget(1, 2, average_button)

        end_button = QtWidgets.QPushButton("Use TV End")
        end_button.clicked.connect(lambda: self._apply_tv_dlong_to_row(2))
        table.setCellWidget(2, 2, end_button)
        return table

    def _populate(self, params: Type6CameraParameters) -> None:
        values = [
            (params.start_point, params.start_zoom),
            (params.middle_point, params.middle_point_zoom),
            (params.end_point, params.end_zoom),
        ]
        with QtCore.QSignalBlocker(self._table):
            for row, (dlong, zoom) in enumerate(values):
                self._table.item(row, 0).setText(str(dlong))
                self._table.item(row, 1).setText(str(zoom))

    def _restore_value(self, row: int, column: int) -> None:
        if self._camera is None or self._camera.type6 is None:
            return
        params = self._camera.type6
        value_map = {
            (0, 0): params.start_point,
            (0, 1): params.start_zoom,
            (1, 0): params.middle_point,
            (1, 1): params.middle_point_zoom,
            (2, 0): params.end_point,
            (2, 1): params.end_zoom,
        }
        value = value_map.get((row, column))
        if value is None:
            return
        with QtCore.QSignalBlocker(self._table):
            self._table.item(row, column).setText(str(value))

    def _apply_tv_dlong_to_row(self, row: int) -> None:
        if self._camera_index is None:
            return
        start_dlong, end_dlong = self._tv_dlongs_provider(self._camera_index)
        if row == 0:
            value = start_dlong
        elif row == 2:
            value = end_dlong
        else:
            return
        if value is None:
            return
        self._table.item(row, 0).setText(str(value))

    def _apply_middle_average(self) -> None:
        if self._camera is None:
            return
        start_item = self._table.item(0, 0)
        end_item = self._table.item(2, 0)
        if start_item is None or end_item is None:
            return
        try:
            start_value = int(start_item.text())
            end_value = int(end_item.text())
        except ValueError:
            return

        if self._track_length is not None and start_value > end_value:
            lap_length = self._track_length
            if lap_length is None or lap_length <= 0:
                return
            total_distance = (lap_length - start_value) + end_value
            midpoint_distance = total_distance // 2
            middle_value = (start_value + midpoint_distance) % lap_length
        else:
            middle_value = (start_value + end_value) // 2
        self._table.item(1, 0).setText(str(middle_value))

    def _handle_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        if self._camera is None or self._camera.type6 is None:
            return
        row = item.row()
        column = item.column()
        text = item.text().strip()
        try:
            value = int(text)
        except ValueError:
            self._restore_value(row, column)
            return

        if column == 0:
            if value < 0:
                self._restore_value(row, column)
                return
            if self._track_length is not None and value > self._track_length:
                self._show_dlong_bounds_error()
                self._restore_value(row, column)
                return

        params = self._camera.type6
        if row == 0:
            if column == 0:
                params.start_point = value
            else:
                params.start_zoom = value
        elif row == 1:
            if column == 0:
                params.middle_point = value
            else:
                params.middle_point_zoom = value
        elif row == 2:
            if column == 0:
                params.end_point = value
            else:
                params.end_zoom = value

    def _show_dlong_bounds_error(self) -> None:
        if self._track_length is None:
            return
        QtWidgets.QMessageBox.warning(
            self,
            "DLONG out of range",
            f"DLONG cannot exceed the track length of {self._track_length}.",
        )


class _Type6ItemDelegate(QtWidgets.QStyledItemDelegate):
    """Limits editing within the Type 6 parameter table."""

    def __init__(self, editor: Type6Editor) -> None:
        super().__init__(editor)
        self._editor = editor

    def createEditor(self, parent, option, index):  # type: ignore[override]
        editor = QtWidgets.QLineEdit(parent)
        if index.column() == 0:
            editor.setValidator(QtGui.QIntValidator(0, 2**31 - 1, editor))
        else:
            editor.setValidator(QtGui.QIntValidator(-2**31, 2**31 - 1, editor))
        return editor
