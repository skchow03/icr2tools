"""Encapsulated TV camera mode panel logic."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.cam.helpers import CameraPosition

from track_viewer.model.camera_models import CameraViewEntry, CameraViewListing


class TvModesPanel(QtWidgets.QWidget):
    """Panel showing TV camera modes with editable DLONGs."""

    cameraSelected = QtCore.pyqtSignal(object)
    dlongsUpdated = QtCore.pyqtSignal(int, object, object)
    modeCountChanged = QtCore.pyqtSignal(int)
    viewChanged = QtCore.pyqtSignal(int)
    addType6Requested = QtCore.pyqtSignal()
    addType2Requested = QtCore.pyqtSignal()
    addType7Requested = QtCore.pyqtSignal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._track_length: Optional[int] = None
        self._views: List[CameraViewListing] = []
        self._cameras: List[CameraPosition] = []
        self._mode_selector = QtWidgets.QComboBox()
        self._mode_selector.addItems(["1", "2"])
        self._mode_selector.currentIndexChanged.connect(
            self._handle_mode_selection_changed
        )
        self._tv_tabs = QtWidgets.QTabWidget()
        self._tv_tabs.setTabBarAutoHide(True)
        self._tv_tabs.setVisible(False)
        self._tv_tabs.currentChanged.connect(self._handle_view_changed)
        self._tv_trees: List[QtWidgets.QTreeWidget] = []
        self._tv_tree_views: Dict[QtWidgets.QTreeWidget, int] = {}
        self._tv_tree_items: Dict[QtWidgets.QTreeWidget, List[QtWidgets.QTreeWidgetItem]] = {}
        self._tv_camera_items: Dict[
            int, List[Tuple[QtWidgets.QTreeWidget, QtWidgets.QTreeWidgetItem]]
        ] = {}

        self._delete_button = QtWidgets.QPushButton("Remove from TV mode")
        self._delete_button.setEnabled(False)
        self._delete_button.clicked.connect(self._handle_delete_camera)
        self._add_type6_button = QtWidgets.QPushButton("Add Panning Camera")
        self._add_type2_button = QtWidgets.QPushButton("Add Alternate Panning Camera")
        self._add_type7_button = QtWidgets.QPushButton("Add Fixed Camera")
        self._add_type6_button.clicked.connect(self.addType6Requested.emit)
        self._add_type2_button.clicked.connect(self.addType2Requested.emit)
        self._add_type7_button.clicked.connect(self.addType7Requested.emit)

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title = QtWidgets.QLabel("TV camera modes")
        title.setStyleSheet("font-weight: bold")
        layout.addWidget(title)
        mode_layout = QtWidgets.QHBoxLayout()
        mode_label = QtWidgets.QLabel("Number of TV modes")
        mode_layout.addWidget(mode_label)
        mode_layout.addStretch(1)
        mode_layout.addWidget(self._mode_selector)
        layout.addLayout(mode_layout)
        camera_action_layout = QtWidgets.QVBoxLayout()
        primary_action_layout = QtWidgets.QHBoxLayout()
        primary_action_layout.addWidget(self._add_type6_button)
        primary_action_layout.addWidget(self._add_type7_button)
        primary_action_layout.addStretch(1)
        secondary_action_layout = QtWidgets.QHBoxLayout()
        secondary_action_layout.addWidget(self._add_type2_button)
        secondary_action_layout.addWidget(self._delete_button)
        secondary_action_layout.addStretch(1)
        camera_action_layout.addLayout(primary_action_layout)
        camera_action_layout.addLayout(secondary_action_layout)
        layout.addLayout(camera_action_layout)
        layout.addWidget(self._tv_tabs)
        self.setLayout(layout)

    def set_mode_count(self, count: int) -> None:
        target_index = 0 if count <= 1 else 1
        with QtCore.QSignalBlocker(self._mode_selector):
            self._mode_selector.setCurrentIndex(target_index)

    def _handle_mode_selection_changed(self, index: int) -> None:
        mode_count = 1 if index <= 0 else 2
        self.modeCountChanged.emit(mode_count)

    def set_track_length(self, length: Optional[int]) -> None:
        self._track_length = length

    def set_views(
        self, views: List[CameraViewListing], cameras: Optional[List[CameraPosition]] = None
    ) -> None:
        self._views = views
        self._cameras = cameras or []
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
                    values = [
                        self._camera_label(entry),
                        self._format_dlong(entry.start_dlong),
                        self._format_dlong(entry.end_dlong),
                    ]
                    item = QtWidgets.QTreeWidgetItem(values)
                    item.setData(0, QtCore.Qt.UserRole, entry.camera_index)
                    item.setData(0, QtCore.Qt.UserRole + 1, view_index)
                    item.setData(0, QtCore.Qt.UserRole + 2, entry_index)
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
        self._update_delete_state()

    def _handle_view_changed(self, index: int) -> None:
        self.viewChanged.emit(index)
        self._update_delete_state()

    def _camera_from_index(self, camera_index: Optional[int]) -> Optional[CameraPosition]:
        if camera_index is None:
            return None
        if camera_index < 0 or camera_index >= len(self._cameras):
            return None
        return self._cameras[camera_index]

    @staticmethod
    def _camera_identifier(camera_type: Optional[int], type_index: Optional[int]) -> str:
        if camera_type == 6:
            type_label = "Pan"
        elif camera_type == 2:
            type_label = "Alt pan"
        elif camera_type == 7:
            type_label = "Fixed"
        else:
            type_label = f"Type {camera_type}" if camera_type is not None else "Type ?"
        index_label = f"#{type_index}" if type_index is not None else "#?"
        return f"{type_label} {index_label}"

    def _camera_label(self, entry: CameraViewEntry) -> str:
        camera = self._camera_from_index(entry.camera_index)
        if camera is not None:
            return self._camera_identifier(camera.camera_type, camera.index)
        fallback_index = (
            entry.type_index if entry.type_index is not None else entry.camera_index
        )
        return self._camera_identifier(entry.camera_type, fallback_index)

    def _camera_options(self) -> list[tuple[str, int]]:
        return [
            (self._camera_identifier(camera.camera_type, camera.index), index)
            for index, camera in enumerate(self._cameras)
        ]

    def entry_for_index(self, model_index: QtCore.QModelIndex) -> Optional[CameraViewEntry]:
        _tree, _item, view_index, entry_index = self._context_for_index(model_index)
        if view_index is None or entry_index is None:
            return None
        if view_index < 0 or view_index >= len(self._views):
            return None
        view = self._views[view_index]
        if entry_index < 0 or entry_index >= len(view.entries):
            return None
        return view.entries[entry_index]

    def populate_camera_editor(
        self, editor: QtWidgets.QComboBox, model_index: QtCore.QModelIndex
    ) -> None:
        editor.clear()
        options = self._camera_options()
        if not options:
            editor.setEnabled(False)
            return
        for label, camera_index in options:
            editor.addItem(label, camera_index)
        editor.setEnabled(True)
        entry = self.entry_for_index(model_index)
        if entry is None:
            return
        current_row = editor.findData(entry.camera_index)
        if current_row < 0:
            current_row = 0
        editor.setCurrentIndex(current_row)

    def commit_camera_editor(
        self, editor: QtWidgets.QComboBox, model_index: QtCore.QModelIndex
    ) -> None:
        tree, item, view_index, entry_index = self._context_for_index(model_index)
        if tree is None or item is None or view_index is None or entry_index is None:
            return
        camera_data = editor.currentData()
        if camera_data is None:
            return
        try:
            camera_index = int(camera_data)
        except (TypeError, ValueError):
            return
        self._set_entry_camera(tree, item, view_index, entry_index, camera_index)

    def _context_for_index(
        self, model_index: QtCore.QModelIndex
    ) -> tuple[
        Optional[QtWidgets.QTreeWidget],
        Optional[QtWidgets.QTreeWidgetItem],
        Optional[int],
        Optional[int],
    ]:
        model = model_index.model()
        tree = next((candidate for candidate in self._tv_trees if candidate.model() is model), None)
        if tree is None:
            return None, None, None, None
        item = tree.itemFromIndex(model_index)
        view_index = self._tv_tree_views.get(tree)
        entry_index_data = item.data(0, QtCore.Qt.UserRole + 2) if item else None
        entry_index: Optional[int]
        if entry_index_data is None:
            entry_index = None
        else:
            try:
                entry_index = int(entry_index_data)
            except (TypeError, ValueError):
                entry_index = None
        return tree, item, view_index, entry_index

    def _set_entry_camera(
        self,
        tree: QtWidgets.QTreeWidget,
        item: QtWidgets.QTreeWidgetItem,
        view_index: int,
        entry_index: int,
        camera_index: int,
    ) -> None:
        if view_index < 0 or view_index >= len(self._views):
            return
        view = self._views[view_index]
        if entry_index < 0 or entry_index >= len(view.entries):
            return
        entry = view.entries[entry_index]
        camera = self._camera_from_index(camera_index)
        if camera is None:
            return
        previous_camera_index = entry.camera_index
        entry.camera_index = camera_index
        entry.type_index = camera.index
        entry.camera_type = camera.camera_type
        entry.mark = camera.camera_type
        with QtCore.QSignalBlocker(tree):
            item.setData(0, QtCore.Qt.UserRole, camera_index)
            item.setText(0, self._camera_label(entry))
        self._update_camera_item_reference(previous_camera_index, camera_index, tree, item)

    def _update_camera_item_reference(
        self,
        previous_camera_index: Optional[int],
        new_camera_index: int,
        tree: QtWidgets.QTreeWidget,
        item: QtWidgets.QTreeWidgetItem,
    ) -> None:
        if previous_camera_index is not None:
            previous_items = self._tv_camera_items.get(previous_camera_index, [])
            self._tv_camera_items[previous_camera_index] = [
                pair for pair in previous_items if pair != (tree, item)
            ]
            if not self._tv_camera_items[previous_camera_index]:
                del self._tv_camera_items[previous_camera_index]
        self._tv_camera_items.setdefault(new_camera_index, []).append((tree, item))

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
        tree.setColumnCount(3)
        tree.setHeaderLabels(["Camera", "Start", "End"])
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
            self._update_delete_state()
            return
        data = current.data(0, QtCore.Qt.UserRole)
        if data is None:
            self.cameraSelected.emit(None)
            self._update_delete_state()
            return
        try:
            camera_index = int(data)
        except (TypeError, ValueError):
            self.cameraSelected.emit(None)
            self._update_delete_state()
            return
        self.cameraSelected.emit(camera_index)
        self._update_delete_state()

    def _handle_tv_item_changed(
        self, item: QtWidgets.QTreeWidgetItem, column: int
    ) -> None:
        tree = self.sender()
        if not isinstance(tree, QtWidgets.QTreeWidget):
            return
        if column not in (1, 2):
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
        editable_types = {2, 6, 7}

        if column in (1, 2) and entry.camera_type not in editable_types:
            return

        if column == 0:
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

        if column == 1:
            entry.start_dlong = new_value
            self.dlongsUpdated.emit(entry.camera_index, new_value, None)
            self._align_previous_camera_end(tree, view_index, entry_index, new_value)
        elif column == 2:
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
        if column == 1:
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
            self._refresh_item_text(tree, previous_item, 2, new_start)
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
            self._refresh_item_text(tree, next_item, 1, new_end)
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

    def _handle_delete_camera(self) -> None:
        tree = self._current_tree()
        if tree is None:
            return
        item = tree.currentItem()
        if item is None:
            return
        view_index = self._tv_tree_views.get(tree)
        if view_index is None or view_index < 0 or view_index >= len(self._views):
            return
        entry_index_data = item.data(0, QtCore.Qt.UserRole + 2)
        if entry_index_data is None:
            return
        try:
            entry_index = int(entry_index_data)
        except (TypeError, ValueError):
            return
        view = self._views[view_index]
        if entry_index < 0 or entry_index >= len(view.entries):
            return
        deleted_entry = view.entries.pop(entry_index)
        deleted_start = deleted_entry.start_dlong
        if view.entries:
            next_index = entry_index if entry_index < len(view.entries) else 0
            next_entry = view.entries[next_index]
            next_entry.start_dlong = deleted_start
            previous_index = (next_index - 1) % len(view.entries)
            previous_entry = view.entries[previous_index]
            previous_entry.end_dlong = deleted_start
            self.dlongsUpdated.emit(next_entry.camera_index, next_entry.start_dlong, None)
            self.dlongsUpdated.emit(previous_entry.camera_index, None, previous_entry.end_dlong)
        self._refresh_tv_tree(view_index)
        if view.entries:
            tree = self._tv_trees[view_index]
            items = self._tv_tree_items.get(tree, [])
            next_index = entry_index if entry_index < len(items) else 0
            if 0 <= next_index < len(items):
                with QtCore.QSignalBlocker(tree):
                    tree.setCurrentItem(items[next_index])
        self._update_delete_state()

    def _current_tree(self) -> Optional[QtWidgets.QTreeWidget]:
        tab_index = self._tv_tabs.currentIndex()
        if tab_index < 0 or tab_index >= len(self._tv_trees):
            return None
        return self._tv_trees[tab_index]

    def _refresh_tv_tree(self, view_index: int) -> None:
        if view_index < 0 or view_index >= len(self._tv_trees):
            return
        tree = self._tv_trees[view_index]
        self._remove_tree_camera_items(tree)
        view = self._views[view_index]
        items: List[QtWidgets.QTreeWidgetItem] = []
        with QtCore.QSignalBlocker(tree):
            tree.clear()
            for entry_index, entry in enumerate(view.entries):
                values = [
                    self._camera_label(entry),
                    self._format_dlong(entry.start_dlong),
                    self._format_dlong(entry.end_dlong),
                ]
                item = QtWidgets.QTreeWidgetItem(values)
                item.setData(0, QtCore.Qt.UserRole, entry.camera_index)
                item.setData(0, QtCore.Qt.UserRole + 1, view_index)
                item.setData(0, QtCore.Qt.UserRole + 2, entry_index)
                item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)
                tree.addTopLevelItem(item)
                self._tv_camera_items.setdefault(entry.camera_index, []).append(
                    (tree, item)
                )
                items.append(item)
        self._tv_tree_items[tree] = items

    def _remove_tree_camera_items(self, tree: QtWidgets.QTreeWidget) -> None:
        items = self._tv_tree_items.get(tree, [])
        for item in items:
            camera_index_data = item.data(0, QtCore.Qt.UserRole)
            if camera_index_data is None:
                continue
            try:
                camera_index = int(camera_index_data)
            except (TypeError, ValueError):
                continue
            camera_items = self._tv_camera_items.get(camera_index, [])
            self._tv_camera_items[camera_index] = [
                pair for pair in camera_items if pair != (tree, item)
            ]
            if not self._tv_camera_items[camera_index]:
                del self._tv_camera_items[camera_index]
        if tree in self._tv_tree_items:
            del self._tv_tree_items[tree]

    def _update_delete_state(self) -> None:
        tree = self._current_tree()
        if tree is None:
            self._delete_button.setEnabled(False)
            return
        self._delete_button.setEnabled(tree.currentItem() is not None)

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
        if index.column() == 0:
            return QtWidgets.QComboBox(parent)
        if index.column() in (1, 2):
            entry = self._panel.entry_for_index(index)
            if entry is None or entry.camera_type not in {2, 6, 7}:
                return None
            editor = QtWidgets.QLineEdit(parent)
            editor.setValidator(QtGui.QIntValidator(0, 2**31 - 1, editor))
            return editor
        return None

    def setEditorData(self, editor, index):  # type: ignore[override]
        if index.column() == 0 and isinstance(editor, QtWidgets.QComboBox):
            self._panel.populate_camera_editor(editor, index)
            return
        super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):  # type: ignore[override]
        if index.column() == 0 and isinstance(editor, QtWidgets.QComboBox):
            self._panel.commit_camera_editor(editor, index)
            return
        super().setModelData(editor, model, index)
