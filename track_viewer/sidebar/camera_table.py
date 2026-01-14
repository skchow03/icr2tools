"""Editable camera coordinate table widget."""
from __future__ import annotations

from typing import Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.cam.helpers import CameraPosition


class CameraCoordinateTable(QtWidgets.QTableWidget):
    """Displays and edits a single camera's world coordinates."""

    positionUpdated = QtCore.pyqtSignal(int, object, object, object)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(1, 3, parent)
        self._camera_index: Optional[int] = None
        self._camera: Optional[CameraPosition] = None
        self.setHorizontalHeaderLabels(["X", "Y", "Z"])
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setAlternatingRowColors(True)
        self.horizontalHeader().setStretchLastSection(True)
        self.verticalHeader().setVisible(False)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked
            | QtWidgets.QAbstractItemView.SelectedClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed
        )
        self.setItemDelegate(_CameraCoordinateDelegate(self))
        self.itemChanged.connect(self._handle_item_changed)
        self.setEnabled(False)

        for column in range(3):
            item = QtWidgets.QTableWidgetItem()
            item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)
            self.setItem(0, column, item)
        QtCore.QTimer.singleShot(0, self._set_compact_height)

    def set_camera(self, index: Optional[int], camera: Optional[CameraPosition]) -> None:
        self._camera_index = index
        self._camera = camera
        with QtCore.QSignalBlocker(self):
            if camera is None:
                self.setEnabled(False)
                for column in range(3):
                    self.item(0, column).setText("")
                self.setCurrentCell(-1, -1)
                return

            for column, value in enumerate((camera.x, camera.y, camera.z)):
                self.item(0, column).setText(str(value))
            self.setEnabled(True)
            self.setCurrentCell(0, 0)

    def _handle_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        if self._camera is None or self._camera_index is None:
            return
        column = item.column()
        if column not in (0, 1, 2):
            return

        text = item.text().strip()
        try:
            value = int(text)
        except ValueError:
            self._restore_value(column)
            return

        if column == 0:
            self._camera.x = value
        elif column == 1:
            self._camera.y = value
        else:
            self._camera.z = value

        self.positionUpdated.emit(self._camera_index, self._camera.x, self._camera.y, self._camera.z)

    def _restore_value(self, column: int) -> None:
        if self._camera is None:
            return
        value_map = {0: self._camera.x, 1: self._camera.y, 2: self._camera.z}
        value = value_map.get(column)
        if value is None:
            return
        with QtCore.QSignalBlocker(self):
            self.item(0, column).setText(str(value))

    def _set_compact_height(self) -> None:
        header_height = self.horizontalHeader().height()
        row_height = self.rowHeight(0) if self.rowCount() else 0
        frame = self.frameWidth() * 2
        self.setFixedHeight(header_height + row_height + frame + 2)


class _CameraCoordinateDelegate(QtWidgets.QStyledItemDelegate):
    """Provides validation for editable camera coordinate cells."""

    def __init__(self, table: CameraCoordinateTable) -> None:
        super().__init__(table)
        self._table = table

    def createEditor(self, parent, option, index):  # type: ignore[override]
        if index.column() not in (0, 1, 2):
            return None
        editor = QtWidgets.QLineEdit(parent)
        editor.setValidator(QtGui.QIntValidator(-2**31, 2**31 - 1, editor))
        return editor
