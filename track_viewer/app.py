"""Simple Qt application shell for the standalone track viewer."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PyQt5 import QtWidgets, QtCore, QtGui

from icr2_core.cam.helpers import CameraPosition, Type6CameraParameters
from track_viewer.camera_models import CameraViewListing
from track_viewer.preview_widget import TrackPreviewWidget


class TrackViewerApp(QtWidgets.QApplication):
    """Thin wrapper that stores shared state for the viewer."""

    def __init__(self, argv: List[str]):
        super().__init__(argv)
        self.setQuitOnLastWindowClosed(True)

        self.installation_path: Optional[Path] = None
        self.tracks: List[str] = []
        self.window: Optional["TrackViewerWindow"] = None

    def update_tracks(self, tracks: List[str]) -> None:
        self.tracks = tracks


class CoordinateSidebar(QtWidgets.QFrame):
    """Utility sidebar that mirrors cursor, flag and camera details."""

    cameraSelectionChanged = QtCore.pyqtSignal(object)
    cameraDlongsUpdated = QtCore.pyqtSignal(int, object, object)
    cameraPositionUpdated = QtCore.pyqtSignal(int, object, object, object)

    def __init__(self) -> None:
        super().__init__()
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setMinimumWidth(220)
        self._track_length: int | None = None

        self._cursor_x = self._create_readonly_field("–")
        self._cursor_y = self._create_readonly_field("–")
        self._flag_x = self._create_readonly_field("–")
        self._flag_y = self._create_readonly_field("–")
        self._camera_list = QtWidgets.QListWidget()
        self._camera_list.setMinimumHeight(120)
        self._camera_list.currentRowChanged.connect(self._on_camera_selected)
        self._tv_tabs_label = QtWidgets.QLabel("TV camera modes")
        self._tv_tabs_label.setStyleSheet("font-weight: bold")
        self._tv_tabs = QtWidgets.QTabWidget()
        self._tv_tabs.setTabBarAutoHide(True)
        self._tv_tabs.setVisible(False)
        self._tv_tabs_label.setVisible(False)
        self._tv_trees: List[QtWidgets.QTreeWidget] = []
        self._tv_tree_views: Dict[QtWidgets.QTreeWidget, int] = {}
        self._tv_tree_items: Dict[QtWidgets.QTreeWidget, List[QtWidgets.QTreeWidgetItem]] = {}
        self._tv_camera_items: Dict[
            int, Tuple[QtWidgets.QTreeWidget, QtWidgets.QTreeWidgetItem]
        ] = {}
        self._camera_views: List[CameraViewListing] = []
        self._camera_details = QtWidgets.QLabel("Select a camera to inspect.")
        self._camera_details.setTextFormat(QtCore.Qt.RichText)
        self._camera_details.setWordWrap(True)
        self._camera_details.setAlignment(QtCore.Qt.AlignTop)
        self._camera_details.setStyleSheet("font-size: 12px")
        self._type6_camera_index: int | None = None
        self._type6_group = QtWidgets.QGroupBox("Type 6 parameters")
        self._type6_group.setVisible(False)
        self._type6_table = self._create_type6_table()
        type6_group_layout = QtWidgets.QVBoxLayout()
        type6_group_layout.addWidget(self._type6_table)
        self._type6_group.setLayout(type6_group_layout)
        self._cameras: List[CameraPosition] = []
        self._selected_camera_index: int | None = None

        layout = QtWidgets.QVBoxLayout()
        layout.setSpacing(12)

        cursor_title = QtWidgets.QLabel("Cursor position")
        cursor_title.setStyleSheet("font-weight: bold")
        layout.addWidget(cursor_title)
        cursor_form = QtWidgets.QFormLayout()
        cursor_form.addRow("X", self._cursor_x)
        cursor_form.addRow("Y", self._cursor_y)
        layout.addLayout(cursor_form)

        flag_title = QtWidgets.QLabel("Selected flag")
        flag_title.setStyleSheet("font-weight: bold")
        layout.addWidget(flag_title)
        flag_form = QtWidgets.QFormLayout()
        flag_form.addRow("X", self._flag_x)
        flag_form.addRow("Y", self._flag_y)
        layout.addLayout(flag_form)

        hint = QtWidgets.QLabel(
            "Left click to drop/select flags.\n"
            "Right click a flag to remove it."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #bbbbbb; font-size: 11px")
        layout.addWidget(hint)

        camera_title = QtWidgets.QLabel("Track cameras")
        camera_title.setStyleSheet("font-weight: bold")
        layout.addWidget(camera_title)
        layout.addWidget(self._camera_list)

        layout.addWidget(self._tv_tabs_label)
        layout.addWidget(self._tv_tabs)

        details_title = QtWidgets.QLabel("Camera details")
        details_title.setStyleSheet("font-weight: bold")
        layout.addWidget(details_title)
        layout.addWidget(self._camera_details)

        coords_title = QtWidgets.QLabel("World coordinates")
        coords_title.setStyleSheet("font-weight: bold")
        layout.addWidget(coords_title)
        layout.addWidget(self._camera_table)
        layout.addWidget(self._type6_group)

        layout.addStretch(1)
        self.setLayout(layout)

    def set_track_length(self, track_length: Optional[int]) -> None:
        self._track_length = track_length if track_length is not None else None

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
        self._type6_camera_index = None
        self._selected_camera_index = None
        self._type6_group.setVisible(False)
        self._camera_list.blockSignals(True)
        self._camera_list.clear()
        self._camera_table.blockSignals(True)
        self._camera_table.setRowCount(0)
        if not cameras:
            self._camera_list.addItem("(No cameras found)")
            self._camera_list.setEnabled(False)
            self._camera_table.setEnabled(False)
            self._camera_details.setText(
                "This track does not define any camera positions."
            )
            self._camera_list.setCurrentRow(-1)
            self._camera_table.setCurrentCell(-1, -1)
        else:
            for cam in cameras:
                label = f"#{cam.index} (type {cam.camera_type})"
                item = QtWidgets.QListWidgetItem(label)
                self._camera_list.addItem(item)
            self._camera_list.setEnabled(True)
            self._camera_table.setEnabled(False)
            self._camera_list.setCurrentRow(-1)
            self._camera_table.setCurrentCell(-1, -1)
            self._camera_details.setText("Select a camera to inspect.")
        self._camera_list.blockSignals(False)
        self._camera_table.blockSignals(False)
        self._update_tv_camera_tabs(views)

    def select_camera(self, index: int | None) -> None:
        self._camera_list.blockSignals(True)
        self._camera_table.blockSignals(True)
        if index is None:
            self._camera_list.setCurrentRow(-1)
            self._camera_table.setCurrentCell(-1, -1)
        else:
            self._camera_list.setCurrentRow(index)
            if self._camera_table.rowCount():
                self._camera_table.setCurrentCell(0, 0)
        self._camera_list.blockSignals(False)
        self._camera_table.blockSignals(False)
        self._select_tv_camera_item(index)

    def update_selected_camera_details(
        self, index: int | None, camera: Optional[CameraPosition]
    ) -> None:
        if camera is None:
            self._camera_details.setText("Select a camera to inspect.")
            self._type6_camera_index = None
            self._selected_camera_index = None
            self._type6_group.setVisible(False)
            self._populate_camera_position_table(None)
            if index is None:
                self.select_camera(None)
            return
        self._selected_camera_index = index
        details = [f"Index: {camera.index}", f"Type: {camera.camera_type}"]

        self._populate_camera_position_table(camera)

        if camera.camera_type == 6 and camera.type6 is not None:
            details.append("Type 6 parameters can be edited below.")
            self._type6_camera_index = index if index is not None else camera.index
            self._populate_type6_table(camera.type6)
            self._type6_group.setVisible(True)
        else:
            self._type6_camera_index = None
            self._type6_group.setVisible(False)

        self._camera_details.setText("<br>".join(details))
        if index is not None and self._camera_list.currentRow() != index:
            self.select_camera(index)

    def _update_tv_camera_tabs(self, views: List[CameraViewListing]) -> None:
        self._tv_tree_views.clear()
        self._tv_tree_items.clear()
        while self._tv_tabs.count():
            widget = self._tv_tabs.widget(0)
            self._tv_tabs.removeTab(0)
            if widget is not None:
                widget.deleteLater()
        self._tv_camera_items.clear()
        self._tv_trees = []
        if not views:
            self._tv_tabs_label.setVisible(False)
            self._tv_tabs.setVisible(False)
            return
        self._tv_tabs_label.setVisible(True)
        self._tv_tabs.setVisible(True)
        for view_index, view in enumerate(views):
            tree = self._create_tv_tree()
            self._tv_tree_views[tree] = view_index
            items: List[QtWidgets.QTreeWidgetItem] = []
            with QtCore.QSignalBlocker(tree):
                for entry_index, entry in enumerate(view.entries):
                    values = [
                        f"#{entry.camera_index}",
                        f"{entry.camera_type}" if entry.camera_type is not None else "–",
                        self._format_dlong(entry.start_dlong),
                        self._format_dlong(entry.end_dlong),
                    ]
                    item = QtWidgets.QTreeWidgetItem(values)
                    item.setData(0, QtCore.Qt.UserRole, entry.camera_index)
                    item.setData(0, QtCore.Qt.UserRole + 1, view_index)
                    item.setData(0, QtCore.Qt.UserRole + 2, entry_index)
                    if entry.camera_type == 6:
                        item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)
                    tree.addTopLevelItem(item)
                    self._tv_camera_items.setdefault(entry.camera_index, (tree, item))
                    items.append(item)
            container = QtWidgets.QWidget()
            container_layout = QtWidgets.QVBoxLayout()
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.addWidget(tree)
            container.setLayout(container_layout)
            self._tv_tabs.addTab(container, view.label)
            self._tv_trees.append(tree)
            self._tv_tree_items[tree] = items
            tree.itemChanged.connect(self._handle_tv_item_changed)
        self._tv_tabs.setCurrentIndex(0)

    def _create_tv_tree(self) -> QtWidgets.QTreeWidget:
        tree = QtWidgets.QTreeWidget()
        tree.setColumnCount(4)
        tree.setHeaderLabels(["ID", "Type", "Start", "End"])
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        tree.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        tree.setUniformRowHeights(True)
        tree.setMinimumHeight(120)
        tree.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked
            | QtWidgets.QAbstractItemView.SelectedClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed
        )
        tree.setItemDelegate(_TvCameraItemDelegate(self))
        tree.currentItemChanged.connect(self._handle_tv_camera_selected)
        return tree

    def _create_camera_table(self) -> QtWidgets.QTableWidget:
        table = QtWidgets.QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["X", "Y", "Z"])
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked
            | QtWidgets.QAbstractItemView.SelectedClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed
        )
        table.setItemDelegate(_CameraCoordinateDelegate(self))
        table.itemChanged.connect(self._handle_camera_table_item_changed)
        return table

    def _create_type6_table(self) -> QtWidgets.QTableWidget:
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
        table.itemChanged.connect(self._handle_type6_item_changed)
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

    def _populate_camera_position_table(
        self, camera: Optional[CameraPosition]
    ) -> None:
        with QtCore.QSignalBlocker(self._camera_table):
            if camera is None:
                self._camera_table.setRowCount(0)
                self._camera_table.setEnabled(False)
                return

            self._camera_table.setRowCount(1)
            for column, value in enumerate((camera.x, camera.y, camera.z)):
                item = self._camera_table.item(0, column)
                if item is None:
                    item = QtWidgets.QTableWidgetItem()
                    item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)
                    self._camera_table.setItem(0, column, item)
                item.setText(str(value))
            self._camera_table.setEnabled(True)

    def _restore_camera_table_value(self, column: int) -> None:
        if self._selected_camera_index is None:
            return
        if self._selected_camera_index < 0 or self._selected_camera_index >= len(
            self._cameras
        ):
            return
        camera = self._cameras[self._selected_camera_index]
        if camera is None:
            return
        value_map = {0: camera.x, 1: camera.y, 2: camera.z}
        if column not in value_map:
            return
        with QtCore.QSignalBlocker(self._camera_table):
            item = self._camera_table.item(0, column)
            if item is not None:
                item.setText(str(value_map[column]))

    def _handle_camera_table_item_changed(
        self, item: QtWidgets.QTableWidgetItem
    ) -> None:
        column = item.column()
        if column not in (0, 1, 2):
            return
        if self._selected_camera_index is None:
            return
        if self._selected_camera_index < 0 or self._selected_camera_index >= len(
            self._cameras
        ):
            return
        camera = self._cameras[self._selected_camera_index]
        if camera is None:
            return
        text = item.text().strip()
        try:
            value = int(text)
        except ValueError:
            self._restore_camera_table_value(column)
            return

        if column == 0:
            camera.x = value
        elif column == 1:
            camera.y = value
        else:
            camera.z = value

        self.update_selected_camera_details(self._selected_camera_index, camera)
        self.cameraPositionUpdated.emit(
            self._selected_camera_index, camera.x, camera.y, camera.z
        )

    def _populate_type6_table(self, params: Type6CameraParameters) -> None:
        values = [
            (params.start_point, params.start_zoom),
            (params.middle_point, params.middle_point_zoom),
            (params.end_point, params.end_zoom),
        ]
        with QtCore.QSignalBlocker(self._type6_table):
            for row, (dlong, zoom) in enumerate(values):
                self._type6_table.item(row, 0).setText(str(dlong))
                self._type6_table.item(row, 1).setText(str(zoom))

    def _restore_type6_value(self, row: int, column: int) -> None:
        if self._type6_camera_index is None:
            return
        if self._type6_camera_index < 0 or self._type6_camera_index >= len(self._cameras):
            return
        camera = self._cameras[self._type6_camera_index]
        if camera.type6 is None:
            return
        params = camera.type6
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
        with QtCore.QSignalBlocker(self._type6_table):
            self._type6_table.item(row, column).setText(str(value))

    def _apply_tv_dlong_to_row(self, row: int) -> None:
        if self._type6_camera_index is None or not self._camera_views:
            return
        start_dlong, end_dlong = self._camera_tv_dlongs(self._type6_camera_index)
        if row == 0:
            value = start_dlong
        elif row == 2:
            value = end_dlong
        else:
            return
        if value is None:
            return
        self._type6_table.item(row, 0).setText(str(value))

    def _apply_middle_average(self) -> None:
        if self._type6_camera_index is None:
            return
        start_item = self._type6_table.item(0, 0)
        end_item = self._type6_table.item(2, 0)
        if start_item is None or end_item is None:
            return
        try:
            start_value = int(start_item.text())
            end_value = int(end_item.text())
        except ValueError:
            return

        if self._track_length is not None and start_value > end_value:
            lap_length = self._track_length
            if lap_length <= 0:
                return
            total_distance = (lap_length - start_value) + end_value
            midpoint_distance = total_distance // 2
            middle_value = (start_value + midpoint_distance) % lap_length
        else:
            middle_value = (start_value + end_value) // 2
        self._type6_table.item(1, 0).setText(str(middle_value))

    def _camera_tv_dlongs(self, camera_index: int) -> tuple[Optional[int], Optional[int]]:
        start_dlong: Optional[int] = None
        end_dlong: Optional[int] = None
        for view in self._camera_views:
            for entry in view.entries:
                if entry.camera_index != camera_index:
                    continue
                if start_dlong is None:
                    start_dlong = entry.start_dlong
                if end_dlong is None:
                    end_dlong = entry.end_dlong
                if start_dlong is not None and end_dlong is not None:
                    return start_dlong, end_dlong
        return start_dlong, end_dlong

    def _handle_type6_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        if self._type6_camera_index is None:
            return
        if self._type6_camera_index < 0 or self._type6_camera_index >= len(self._cameras):
            return
        camera = self._cameras[self._type6_camera_index]
        if camera.type6 is None:
            return
        row = item.row()
        column = item.column()
        text = item.text().strip()
        try:
            value = int(text)
        except ValueError:
            self._restore_type6_value(row, column)
            return

        if column == 0:
            if value < 0:
                self._restore_type6_value(row, column)
                return
            if self._track_length is not None and value > self._track_length:
                self._show_dlong_bounds_error()
                self._restore_type6_value(row, column)
                return

        params = camera.type6
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
        else:
            return

        self._camera_details.setText(self._camera_details.text())

    def _handle_tv_camera_selected(
        self,
        current: Optional[QtWidgets.QTreeWidgetItem],
        _previous: Optional[QtWidgets.QTreeWidgetItem],
    ) -> None:
        tree = self.sender()
        if not isinstance(tree, QtWidgets.QTreeWidget):
            return
        if current is None:
            self.cameraSelectionChanged.emit(None)
            return
        data = current.data(0, QtCore.Qt.UserRole)
        if data is None:
            self.cameraSelectionChanged.emit(None)
            return
        try:
            camera_index = int(data)
        except (TypeError, ValueError):
            self.cameraSelectionChanged.emit(None)
            return
        self.cameraSelectionChanged.emit(camera_index)

    def _select_tv_camera_item(self, index: int | None) -> None:
        for tree in self._tv_trees:
            blocker = QtCore.QSignalBlocker(tree)
            tree.setCurrentItem(None)
        if index is None:
            return
        tree_item = self._tv_camera_items.get(index)
        if not tree_item:
            return
        tree, item = tree_item
        with QtCore.QSignalBlocker(tree):
            tree.setCurrentItem(item)
        try:
            tab_index = self._tv_trees.index(tree)
        except ValueError:
            return
        self._tv_tabs.setCurrentIndex(tab_index)

    @staticmethod
    def _format_dlong(value: Optional[int]) -> str:
        if value is None:
            return "–"
        return f"{value}"

    def _handle_tv_item_changed(
        self, item: QtWidgets.QTreeWidgetItem, column: int
    ) -> None:
        tree = self.sender()
        if not isinstance(tree, QtWidgets.QTreeWidget):
            return
        if column not in (2, 3):
            return

        view_index = self._tv_tree_views.get(tree)
        if view_index is None or view_index >= len(self._camera_views):
            return

        entry_index = item.data(0, QtCore.Qt.UserRole + 2)
        if entry_index is None:
            return
        try:
            entry_index = int(entry_index)
        except (TypeError, ValueError):
            return

        view = self._camera_views[view_index]
        if entry_index < 0 or entry_index >= len(view.entries):
            return
        entry = view.entries[entry_index]
        if entry.camera_type != 6:
            return

        text = item.text(column).strip()
        try:
            new_value = int(text)
        except ValueError:
            self._restore_tv_value(tree, item, column, entry)
            return

        if new_value < 0:
            self._restore_tv_value(tree, item, column, entry)
            return

        if self._track_length is not None and new_value > self._track_length:
            self._show_dlong_bounds_error()
            self._restore_tv_value(tree, item, column, entry)
            return

        if column == 2:
            entry.start_dlong = new_value
            self._sync_camera_dlong(entry.camera_index, start=new_value, end=None)
            self._align_previous_camera_end(tree, view_index, entry_index, new_value)
        elif column == 3:
            entry.end_dlong = new_value
            self._sync_camera_dlong(entry.camera_index, start=None, end=new_value)
            self._align_next_camera_start(tree, view_index, entry_index, new_value)
        self._refresh_item_text(tree, item, column, new_value)

    def _refresh_item_text(
        self,
        tree: QtWidgets.QTreeWidget,
        item: QtWidgets.QTreeWidgetItem,
        column: int,
        value: int,
    ) -> None:
        with QtCore.QSignalBlocker(tree):
            item.setText(column, self._format_dlong(value))

    def _restore_tv_value(
        self,
        tree: QtWidgets.QTreeWidget,
        item: QtWidgets.QTreeWidgetItem,
        column: int,
        entry: CameraViewEntry,
    ) -> None:
        if column == 2:
            value = entry.start_dlong
        else:
            value = entry.end_dlong
        with QtCore.QSignalBlocker(tree):
            item.setText(column, self._format_dlong(value))

    def _align_previous_camera_end(
        self,
        tree: QtWidgets.QTreeWidget,
        view_index: int,
        entry_index: int,
        new_start: int,
    ) -> None:
        view = self._camera_views[view_index]
        if not view.entries:
            return
        previous_index = (entry_index - 1) % len(view.entries)
        previous_entry = view.entries[previous_index]
        previous_entry.end_dlong = new_start
        items = self._tv_tree_items.get(tree, [])
        if previous_index < len(items):
            previous_item = items[previous_index]
            self._refresh_item_text(tree, previous_item, 3, new_start)
        self._sync_camera_dlong(
            previous_entry.camera_index, start=None, end=previous_entry.end_dlong
        )

    def _align_next_camera_start(
        self,
        tree: QtWidgets.QTreeWidget,
        view_index: int,
        entry_index: int,
        new_end: int,
    ) -> None:
        view = self._camera_views[view_index]
        if not view.entries:
            return
        next_index = (entry_index + 1) % len(view.entries)
        next_entry = view.entries[next_index]
        next_entry.start_dlong = new_end
        items = self._tv_tree_items.get(tree, [])
        if next_index < len(items):
            next_item = items[next_index]
            self._refresh_item_text(tree, next_item, 2, new_end)
        self._sync_camera_dlong(
            next_entry.camera_index, start=next_entry.start_dlong, end=None
        )

    def _sync_camera_dlong(
        self, camera_index: int, start: Optional[int], end: Optional[int]
    ) -> None:
        if start is None and end is None:
            return
        self.cameraDlongsUpdated.emit(camera_index, start, end)

    def _show_dlong_bounds_error(self) -> None:
        if self._track_length is None:
            return
        QtWidgets.QMessageBox.warning(
            self,
            "DLONG out of range",
            f"DLONG cannot exceed the track length of {self._track_length}.",
        )

    def _on_camera_selected(self, index: int) -> None:
        if not self._cameras or index < 0 or index >= len(self._cameras):
            self.cameraSelectionChanged.emit(None)
            return
        self.cameraSelectionChanged.emit(index)

    def _create_readonly_field(self, placeholder: str) -> QtWidgets.QLineEdit:
        field = QtWidgets.QLineEdit()
        field.setReadOnly(True)
        field.setPlaceholderText(placeholder)
        field.setFocusPolicy(QtCore.Qt.ClickFocus)
        return field

    @staticmethod
    def _format_value(value: float) -> str:
        return f"{value:.2f}"


class _TvCameraItemDelegate(QtWidgets.QStyledItemDelegate):
    """Limits editing within the TV camera modes table."""

    def __init__(self, sidebar: CoordinateSidebar) -> None:
        super().__init__(sidebar)
        self._sidebar = sidebar

    def createEditor(self, parent, option, index):  # type: ignore[override]
        if index.column() not in (2, 3):
            return None
        editor = QtWidgets.QLineEdit(parent)
        editor.setValidator(QtGui.QIntValidator(0, 2**31 - 1, editor))
        return editor


class _CameraCoordinateDelegate(QtWidgets.QStyledItemDelegate):
    """Provides validation for editable camera coordinate cells."""

    def __init__(self, sidebar: CoordinateSidebar) -> None:
        super().__init__(sidebar)
        self._sidebar = sidebar

    def createEditor(self, parent, option, index):  # type: ignore[override]
        if index.column() not in (0, 1, 2):
            return None
        editor = QtWidgets.QLineEdit(parent)
        editor.setValidator(QtGui.QIntValidator(-2**31, 2**31 - 1, editor))
        return editor


class _Type6ItemDelegate(QtWidgets.QStyledItemDelegate):
    """Limits editing within the Type 6 parameter table."""

    def __init__(self, sidebar: CoordinateSidebar) -> None:
        super().__init__(sidebar)
        self._sidebar = sidebar

    def createEditor(self, parent, option, index):  # type: ignore[override]
        editor = QtWidgets.QLineEdit(parent)
        if index.column() == 0:
            editor.setValidator(QtGui.QIntValidator(0, 2**31 - 1, editor))
        else:
            editor.setValidator(QtGui.QIntValidator(-2**31, 2**31 - 1, editor))
        return editor


class TrackViewerWindow(QtWidgets.QMainWindow):
    """Minimal placeholder UI that demonstrates shared state wiring."""

    def __init__(self, app_state: TrackViewerApp):
        super().__init__()
        self.app_state = app_state
        self.app_state.window = self

        self.setWindowTitle("ICR2 Track Viewer")
        self.resize(720, 480)

        self._path_display = QtWidgets.QLineEdit()
        self._path_display.setReadOnly(True)
        self._browse_button = QtWidgets.QPushButton("Select Folder…")
        self._browse_button.clicked.connect(self._select_installation_path)

        self._track_list = QtWidgets.QListWidget()
        self._track_list.currentItemChanged.connect(self._on_track_selected)

        self.visualization_widget = TrackPreviewWidget()
        self.visualization_widget.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self._sidebar = CoordinateSidebar()
        self.visualization_widget.cursorPositionChanged.connect(
            self._sidebar.update_cursor_position
        )
        self.visualization_widget.selectedFlagChanged.connect(
            self._sidebar.update_flag_position
        )
        self.visualization_widget.camerasChanged.connect(self._sidebar.set_cameras)
        self.visualization_widget.selectedCameraChanged.connect(
            self._sidebar.update_selected_camera_details
        )
        self._sidebar.cameraSelectionChanged.connect(
            self._handle_camera_selection_changed
        )
        self._sidebar.cameraDlongsUpdated.connect(
            self._handle_camera_dlongs_updated
        )
        self._sidebar.cameraPositionUpdated.connect(
            self._handle_camera_position_updated
        )
        self._sidebar.set_cameras([], [])
        self._sidebar.update_selected_camera_details(None, None)
        self._center_line_button = QtWidgets.QPushButton("Hide Center Line")
        self._center_line_button.setCheckable(True)
        self._center_line_button.setChecked(True)
        self._center_line_button.toggled.connect(self._toggle_center_line)
        self._toggle_center_line(self._center_line_button.isChecked())

        self._show_cameras_button = QtWidgets.QPushButton("Show Cameras")
        self._show_cameras_button.setCheckable(True)
        self._show_cameras_button.setChecked(True)
        self._show_cameras_button.toggled.connect(
            self.visualization_widget.set_show_cameras
        )

        layout = QtWidgets.QVBoxLayout()
        header = QtWidgets.QHBoxLayout()
        header.addWidget(QtWidgets.QLabel("ICR2 Installation:"))
        header.addWidget(self._path_display, stretch=1)
        header.addWidget(self._browse_button)
        layout.addLayout(header)

        controls = QtWidgets.QHBoxLayout()
        controls.addStretch(1)
        controls.addWidget(self._center_line_button)
        controls.addWidget(self._show_cameras_button)
        layout.addLayout(controls)

        body = QtWidgets.QSplitter()
        body.setOrientation(QtCore.Qt.Horizontal)
        body.addWidget(self._track_list)
        body.addWidget(self.visualization_widget)
        body.addWidget(self._sidebar)
        body.setSizes([200, 420, 200])
        layout.addWidget(body, stretch=1)

        wrapper = QtWidgets.QWidget()
        wrapper.setLayout(layout)
        self.setCentralWidget(wrapper)

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------
    def _select_installation_path(self) -> None:
        start_dir = str(self.app_state.installation_path or Path.home())
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Select IndyCar Racing II folder",
            start_dir,
        )
        if folder:
            self.app_state.installation_path = Path(folder)
            self._path_display.setText(str(self.app_state.installation_path))
            self._load_tracks()

    def _tracks_root(self) -> Optional[Path]:
        if not self.app_state.installation_path:
            return None
        candidates = [
            self.app_state.installation_path / "TRACKS",
            self.app_state.installation_path / "tracks",
        ]
        for candidate in candidates:
            if candidate.exists() and candidate.is_dir():
                return candidate
        return None

    def _load_tracks(self) -> None:
        track_root = self._tracks_root()
        self._track_list.clear()
        self.visualization_widget.clear()
        self._sidebar.set_track_length(None)

        if not track_root:
            self.app_state.update_tracks([])
            self._track_list.addItem("(TRACKS folder not found)")
            self._track_list.setEnabled(False)
            return

        folders = [
            path
            for path in sorted(track_root.iterdir(), key=lambda p: p.name.lower())
            if path.is_dir()
        ]
        self.app_state.update_tracks([folder.name for folder in folders])
        if not folders:
            self._track_list.addItem("(No track folders found)")
            self._track_list.setEnabled(False)
            return

        self._track_list.setEnabled(True)
        for folder in folders:
            item = QtWidgets.QListWidgetItem(folder.name)
            item.setData(QtCore.Qt.UserRole, folder)
            self._track_list.addItem(item)
        self._track_list.setCurrentRow(0)

    def _on_track_selected(
        self,
        current: Optional[QtWidgets.QListWidgetItem],
        _previous: Optional[QtWidgets.QListWidgetItem],
    ) -> None:
        if not current:
            self.visualization_widget.clear()
            self._sidebar.set_track_length(None)
            return

        folder = current.data(QtCore.Qt.UserRole)
        if not isinstance(folder, Path):
            self.visualization_widget.clear("Select a valid track folder.")
            self._sidebar.set_track_length(None)
            return

        self.visualization_widget.load_track(folder)
        self._sidebar.set_track_length(self.visualization_widget.track_length())

    def _toggle_center_line(self, enabled: bool) -> None:
        text = "Hide Center Line" if enabled else "Show Center Line"
        self._center_line_button.setText(text)
        self.visualization_widget.set_show_center_line(enabled)

    def _handle_camera_selection_changed(self, index: Optional[int]) -> None:
        self.visualization_widget.set_selected_camera(index)

    def _handle_camera_dlongs_updated(
        self, camera_index: int, start: Optional[int], end: Optional[int]
    ) -> None:
        self.visualization_widget.update_camera_dlongs(camera_index, start, end)

    def _handle_camera_position_updated(
        self, index: int, x: Optional[int], y: Optional[int], z: Optional[int]
    ) -> None:
        self.visualization_widget.update_camera_position(index, x, y, z)
