"""Encapsulated TV camera mode panel logic."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

from track_viewer.camera_models import CameraViewEntry, CameraViewListing


class TvModesPanel(QtWidgets.QWidget):
    """Panel showing TV camera modes with editable DLONGs."""

    cameraSelected = QtCore.pyqtSignal(object)
    dlongsUpdated = QtCore.pyqtSignal(int, object, object)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._track_length: Optional[int] = None
        self._views: List[CameraViewListing] = []
        self._tv_tabs = QtWidgets.QTabWidget()
        self._tv_tabs.setTabBarAutoHide(True)
        self._tv_tabs.setVisible(False)
        self._tv_trees: List[QtWidgets.QTreeWidget] = []
        self._tv_tree_views: Dict[QtWidgets.QTreeWidget, int] = {}
        self._tv_tree_items: Dict[QtWidgets.QTreeWidget, List[QtWidgets.QTreeWidgetItem]] = {}
        self._tv_camera_items: Dict[
            int, List[Tuple[QtWidgets.QTreeWidget, QtWidgets.QTreeWidgetItem]]
        ] = {}

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title = QtWidgets.QLabel("TV camera modes")
        title.setStyleSheet("font-weight: bold")
        layout.addWidget(title)
        layout.addWidget(self._tv_tabs)
        self.setLayout(layout)

    def set_track_length(self, length: Optional[int]) -> None:
        self._track_length = length

    def set_views(self, views: List[CameraViewListing]) -> None:
        self._views = views
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
            self._tv_tabs.setVisible(False)
            return
        self._tv_tabs.setVisible(True)
        for view_index, view in enumerate(views):
            tree = self._create_tv_tree()
            self._tv_tree_views[tree] = view_index
            items: List[QtWidgets.QTreeWidgetItem] = []
            with QtCore.QSignalBlocker(tree):
                for entry_index, entry in enumerate(view.entries):
                    display_index = entry.type_index
                    values = [
                        f"#{display_index}" if display_index is not None else f"#{entry.camera_index}",
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
                    self._tv_camera_items.setdefault(entry.camera_index, []).append(
                        (tree, item)
                    )
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

    def select_camera(self, index: int | None) -> None:
        for tree in self._tv_trees:
            blocker = QtCore.QSignalBlocker(tree)
            tree.setCurrentItem(None)
        if index is None:
            return
        tree_items = self._tv_camera_items.get(index)
        if not tree_items:
            return
        tree: Optional[QtWidgets.QTreeWidget] = None
        item: Optional[QtWidgets.QTreeWidgetItem] = None
        tab_index = self._tv_tabs.currentIndex()
        if 0 <= tab_index < len(self._tv_trees):
            current_tree = self._tv_trees[tab_index]
            for candidate_tree, candidate_item in tree_items:
                if candidate_tree is current_tree:
                    tree = candidate_tree
                    item = candidate_item
                    break
        if tree is None and tree_items:
            tree, item = tree_items[0]
        if tree is None or item is None:
            return
        with QtCore.QSignalBlocker(tree):
            tree.setCurrentItem(item)
        try:
            tab_index = self._tv_trees.index(tree)
        except ValueError:
            return
        self._tv_tabs.setCurrentIndex(tab_index)

    def camera_dlongs(self, camera_index: int) -> tuple[Optional[int], Optional[int]]:
        start_dlong: Optional[int] = None
        end_dlong: Optional[int] = None
        for view in self._views:
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

    def _handle_tv_camera_selected(
        self,
        current: Optional[QtWidgets.QTreeWidgetItem],
        _previous: Optional[QtWidgets.QTreeWidgetItem],
    ) -> None:
        tree = self.sender()
        if not isinstance(tree, QtWidgets.QTreeWidget):
            return
        if current is None:
            self.cameraSelected.emit(None)
            return
        data = current.data(0, QtCore.Qt.UserRole)
        if data is None:
            self.cameraSelected.emit(None)
            return
        try:
            camera_index = int(data)
        except (TypeError, ValueError):
            self.cameraSelected.emit(None)
            return
        self.cameraSelected.emit(camera_index)

    def _handle_tv_item_changed(
        self, item: QtWidgets.QTreeWidgetItem, column: int
    ) -> None:
        tree = self.sender()
        if not isinstance(tree, QtWidgets.QTreeWidget):
            return
        if column not in (2, 3):
            return

        view_index = self._tv_tree_views.get(tree)
        if view_index is None or view_index >= len(self._views):
            return

        entry_index = item.data(0, QtCore.Qt.UserRole + 2)
        if entry_index is None:
            return
        try:
            entry_index = int(entry_index)
        except (TypeError, ValueError):
            return

        view = self._views[view_index]
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
            self.dlongsUpdated.emit(entry.camera_index, new_value, None)
            self._align_previous_camera_end(tree, view_index, entry_index, new_value)
        elif column == 3:
            entry.end_dlong = new_value
            self.dlongsUpdated.emit(entry.camera_index, None, new_value)
            self._align_next_camera_start(tree, view_index, entry_index, new_value)

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
        view = self._views[view_index]
        if not view.entries:
            return
        previous_index = (entry_index - 1) % len(view.entries)
        previous_entry = view.entries[previous_index]
        previous_entry.end_dlong = new_start
        items = self._tv_tree_items.get(tree, [])
        if previous_index < len(items):
            previous_item = items[previous_index]
            self._refresh_item_text(tree, previous_item, 3, new_start)
        self.dlongsUpdated.emit(previous_entry.camera_index, None, previous_entry.end_dlong)

    def _align_next_camera_start(
        self,
        tree: QtWidgets.QTreeWidget,
        view_index: int,
        entry_index: int,
        new_end: int,
    ) -> None:
        view = self._views[view_index]
        if not view.entries:
            return
        next_index = (entry_index + 1) % len(view.entries)
        next_entry = view.entries[next_index]
        next_entry.start_dlong = new_end
        items = self._tv_tree_items.get(tree, [])
        if next_index < len(items):
            next_item = items[next_index]
            self._refresh_item_text(tree, next_item, 2, new_end)
        self.dlongsUpdated.emit(next_entry.camera_index, next_entry.start_dlong, None)

    def _refresh_item_text(
        self,
        tree: QtWidgets.QTreeWidget,
        item: QtWidgets.QTreeWidgetItem,
        column: int,
        value: Optional[int],
    ) -> None:
        with QtCore.QSignalBlocker(tree):
            item.setText(column, self._format_dlong(value))

    def _show_dlong_bounds_error(self) -> None:
        if self._track_length is None:
            return
        QtWidgets.QMessageBox.warning(
            self,
            "DLONG out of range",
            f"DLONG cannot exceed the track length of {self._track_length}.",
        )

    @staticmethod
    def _format_dlong(value: Optional[int]) -> str:
        if value is None:
            return "–"
        return f"{value}"


class _TvCameraItemDelegate(QtWidgets.QStyledItemDelegate):
    """Limits editing within the TV camera modes table."""

    def __init__(self, panel: TvModesPanel) -> None:
        super().__init__(panel)
        self._panel = panel

    def createEditor(self, parent, option, index):  # type: ignore[override]
        if index.column() not in (2, 3):
            return None
        editor = QtWidgets.QLineEdit(parent)
        editor.setValidator(QtGui.QIntValidator(0, 2**31 - 1, editor))
        return editor
