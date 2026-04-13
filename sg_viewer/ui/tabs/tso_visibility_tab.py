from PyQt5 import QtCore
from PyQt5.QtGui import QColor, QBrush, QPainter, QPen, QResizeEvent
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QHeaderView,
    QMessageBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sg_viewer.io.track3d_parser import (
    Track3DObjectList,
    Track3DSectionDlongList,
    parse_track3d,
    parse_track3d_section_dlongs,
    save_object_lists_to_track3d,
    track3d_has_object_lists,
)
from sg_viewer.services.tso_visibility_ranges import build_subsection_dlong_metadata


class TSOVisibilityListWidget(QListWidget):
    orderChanged = QtCore.pyqtSignal()
    contentHeightChanged = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setFlow(QListWidget.TopToBottom)
        self.setWrapping(False)
        self.setSpacing(4)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setDropIndicatorShown(False)
        self._drop_indicator_y: int | None = None

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.update_item_widths()

    def update_item_widths(self) -> None:
        viewport_width = max(self.viewport().width() - 2, 0)
        pill_height = self.fontMetrics().height() + 8
        for index in range(self.count()):
            item = self.item(index)
            if item is None:
                continue
            item.setSizeHint(QtCore.QSize(viewport_width, pill_height))
        self.contentHeightChanged.emit()

    def content_height(self) -> int:
        if self.count() == 0:
            return self.frameWidth() * 2 + 4
        item_height = self.sizeHintForRow(0)
        spacing_total = self.spacing() * max(self.count() - 1, 0)
        return (item_height * self.count()) + spacing_total + (self.frameWidth() * 2) + 4

    def _update_drop_indicator_position(self, event_pos: QtCore.QPoint) -> None:
        indicator_y = self._calculate_drop_indicator_y(event_pos)
        self._drop_indicator_y = indicator_y
        self.viewport().update()

    def _calculate_drop_indicator_y(self, event_pos: QtCore.QPoint) -> int | None:
        if self.count() == 0:
            return self.viewport().height() - 1

        first_item = self.item(0)
        last_item = self.item(self.count() - 1)
        if first_item is None or last_item is None:
            return None

        first_rect = self.visualItemRect(first_item)
        if event_pos.y() <= first_rect.center().y():
            return first_rect.top()

        for row in range(1, self.count()):
            item = self.item(row)
            if item is None:
                continue
            rect = self.visualItemRect(item)
            if event_pos.y() <= rect.center().y():
                return rect.top()

        last_rect = self.visualItemRect(last_item)
        return last_rect.bottom() + 1

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._drop_indicator_y is None:
            return
        painter = QPainter(self.viewport())
        pen = QPen(QColor("#0078d4"))
        pen.setWidth(4)
        painter.setPen(pen)
        left = 1
        right = max(self.viewport().width() - 2, left)
        y = self._drop_indicator_y
        painter.drawLine(left, y, right, y)

        cap_height = 8
        cap_top = y - cap_height // 2
        cap_bottom = y + cap_height // 2
        painter.drawLine(left, cap_top, left, cap_bottom)
        painter.drawLine(right, cap_top, right, cap_bottom)

    def dragMoveEvent(self, event) -> None:
        super().dragMoveEvent(event)
        self._update_drop_indicator_position(event.pos())

    def dragLeaveEvent(self, event) -> None:
        super().dragLeaveEvent(event)
        self._drop_indicator_y = None
        self.viewport().update()

    def dropEvent(self, event):
        super().dropEvent(event)
        self._drop_indicator_y = None
        self.viewport().update()
        self.orderChanged.emit()
        self.contentHeightChanged.emit()


class TrackSectionListWidget(QTableWidget):
    rowSelectionChanged = QtCore.pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.setColumnCount(2)
        self.setHorizontalHeaderLabels(["L sections", "R sections"])
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._flat_items: list[QTableWidgetItem] = []
        self.itemSelectionChanged.connect(self._emit_row_selection_changed)

    def _emit_row_selection_changed(self) -> None:
        item = self.currentItem()
        if item is None:
            self.rowSelectionChanged.emit(-1)
            return
        object_index = item.data(QtCore.Qt.UserRole)
        if isinstance(object_index, int):
            self.rowSelectionChanged.emit(object_index)
            return
        self.rowSelectionChanged.emit(-1)

    def clear(self) -> None:
        self.clearContents()
        self.setRowCount(0)
        self._flat_items = []

    def count(self) -> int:
        return len(self._flat_items)

    def item(self, row: int) -> QTableWidgetItem | None:
        if 0 <= row < len(self._flat_items):
            return self._flat_items[row]
        return None

    def setCurrentRow(self, row: int) -> None:
        item = self.item(row)
        if item is None:
            self.clearSelection()
            return
        self.setCurrentItem(item)

    def set_entries(self, left_entries: list[QTableWidgetItem], right_entries: list[QTableWidgetItem]) -> None:
        row_count = max(len(left_entries), len(right_entries))
        self.clear()
        self.setRowCount(row_count)
        self._flat_items = []
        for row in range(row_count):
            if row < len(left_entries):
                item = left_entries[row]
                self.setItem(row, 0, item)
                self._flat_items.append(item)
            if row < len(right_entries):
                item = right_entries[row]
                self.setItem(row, 1, item)
                self._flat_items.append(item)


class TSOVisibilityReconcileDialog(QDialog):
    def __init__(
        self,
        current_lists: list[Track3DObjectList],
        track3d_lists: list[Track3DObjectList],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Reconcile track.3D ObjectLists")
        self.resize(1100, 620)

        self._current_lists = [
            Track3DObjectList(side=entry.side, section=entry.section, sub_index=entry.sub_index, tso_ids=list(entry.tso_ids))
            for entry in current_lists
        ]
        self._track3d_lists = [
            Track3DObjectList(side=entry.side, section=entry.section, sub_index=entry.sub_index, tso_ids=list(entry.tso_ids))
            for entry in track3d_lists
        ]

        layout = QVBoxLayout(self)
        summary = QLabel(
            "Compare the ObjectLists already loaded in SG Viewer against the selected track.3D file. "
            "Use the commands below to copy matching rows or add missing rows before applying the result."
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        grid = QGridLayout()
        layout.addLayout(grid, 1)

        self.current_list_widget = QListWidget(self)
        self.track3d_list_widget = QListWidget(self)
        self.current_list_widget.setSelectionMode(QListWidget.SingleSelection)
        self.track3d_list_widget.setSelectionMode(QListWidget.SingleSelection)

        grid.addWidget(QLabel("Current project ObjectLists"), 0, 0)
        grid.addWidget(QLabel("Selected track.3D ObjectLists"), 0, 2)
        grid.addWidget(self.current_list_widget, 1, 0)

        command_column = QVBoxLayout()
        self.match_button = QPushButton("Match Same Key")
        self.copy_to_current_button = QPushButton("Copy .3D → Current")
        self.copy_all_matching_button = QPushButton("Copy All Matching")
        self.add_selected_button = QPushButton("Add Selected .3D Row")
        self.add_missing_button = QPushButton("Add Missing .3D Rows")
        self.delete_current_button = QPushButton("Delete Selected Current Row")
        self.copy_current_ids_button = QPushButton("Copy Current TSOs")
        self.copy_track3d_ids_button = QPushButton("Copy .3D TSOs")
        self.sort_lists_button = QPushButton("Sort Both Lists")
        for button in (
            self.match_button,
            self.copy_to_current_button,
            self.copy_all_matching_button,
            self.add_selected_button,
            self.add_missing_button,
            self.delete_current_button,
            self.copy_current_ids_button,
            self.copy_track3d_ids_button,
            self.sort_lists_button,
        ):
            command_column.addWidget(button)
        command_column.addStretch(1)
        grid.addLayout(command_column, 1, 1)
        grid.addWidget(self.track3d_list_widget, 1, 2)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.current_list_widget.currentRowChanged.connect(self._sync_selection_to_track3d)
        self.track3d_list_widget.currentRowChanged.connect(self._sync_selection_to_current)
        self.match_button.clicked.connect(self._match_same_key)
        self.copy_to_current_button.clicked.connect(self._copy_selected_track3d_to_current)
        self.copy_all_matching_button.clicked.connect(self._copy_all_matching_rows)
        self.add_selected_button.clicked.connect(self._add_selected_track3d_row)
        self.add_missing_button.clicked.connect(self._add_missing_track3d_rows)
        self.delete_current_button.clicked.connect(self._delete_selected_current_row)
        self.copy_current_ids_button.clicked.connect(
            lambda: self._copy_selected_ids(self.current_list_widget, self._current_lists)
        )
        self.copy_track3d_ids_button.clicked.connect(
            lambda: self._copy_selected_ids(self.track3d_list_widget, self._track3d_lists)
        )
        self.sort_lists_button.clicked.connect(self._sort_both_lists)

        self._refresh_lists()
        if self.current_list_widget.count() > 0:
            self.current_list_widget.setCurrentRow(0)
        elif self.track3d_list_widget.count() > 0:
            self.track3d_list_widget.setCurrentRow(0)

    @staticmethod
    def _entry_key(entry: Track3DObjectList) -> tuple[str, int, int]:
        return (str(entry.side), int(entry.section), int(entry.sub_index))

    @classmethod
    def _format_entry(cls, entry: Track3DObjectList) -> str:
        tso_text = ", ".join(f"__TSO{tso_id}" for tso_id in entry.tso_ids) if entry.tso_ids else "(empty)"
        return f"{entry.side} / {entry.section} / {entry.sub_index} — {tso_text}"

    @staticmethod
    def _sort_key(entry: Track3DObjectList) -> tuple[int, int, int]:
        side = str(entry.side).strip().upper()
        side_order = 0 if side == "L" else 1 if side == "R" else 2
        return (side_order, int(entry.section), int(entry.sub_index))

    @staticmethod
    def _mark_missing_item(item: QListWidgetItem) -> None:
        item.setForeground(QBrush(QColor("red")))

    def _refresh_lists(self) -> None:
        self.current_list_widget.blockSignals(True)
        self.track3d_list_widget.blockSignals(True)
        current_row = self.current_list_widget.currentRow()
        track3d_row = self.track3d_list_widget.currentRow()
        self.current_list_widget.clear()
        self.track3d_list_widget.clear()
        current_keys = {self._entry_key(entry) for entry in self._current_lists}
        track3d_keys = {self._entry_key(entry) for entry in self._track3d_lists}
        for index, entry in enumerate(self._current_lists):
            item = QListWidgetItem(self._format_entry(entry))
            if self._entry_key(entry) not in track3d_keys:
                item.setText(f"{item.text()}  [missing in .3D]")
                self._mark_missing_item(item)
            item.setData(QtCore.Qt.UserRole, index)
            self.current_list_widget.addItem(item)
        for index, entry in enumerate(self._track3d_lists):
            item = QListWidgetItem(self._format_entry(entry))
            if self._entry_key(entry) not in current_keys:
                item.setText(f"{item.text()}  [missing in project]")
                self._mark_missing_item(item)
            item.setData(QtCore.Qt.UserRole, index)
            self.track3d_list_widget.addItem(item)
        self.current_list_widget.blockSignals(False)
        self.track3d_list_widget.blockSignals(False)
        if 0 <= current_row < self.current_list_widget.count():
            self.current_list_widget.setCurrentRow(current_row)
        if 0 <= track3d_row < self.track3d_list_widget.count():
            self.track3d_list_widget.setCurrentRow(track3d_row)

    def _find_row_by_key(
        self,
        entries: list[Track3DObjectList],
        key: tuple[str, int, int],
    ) -> int:
        for index, entry in enumerate(entries):
            if self._entry_key(entry) == key:
                return index
        return -1

    def _sync_selection_to_track3d(self, row: int) -> None:
        if row < 0 or row >= len(self._current_lists):
            return
        match_row = self._find_row_by_key(self._track3d_lists, self._entry_key(self._current_lists[row]))
        if match_row >= 0:
            self.track3d_list_widget.blockSignals(True)
            self.track3d_list_widget.setCurrentRow(match_row)
            self.track3d_list_widget.blockSignals(False)

    def _sync_selection_to_current(self, row: int) -> None:
        if row < 0 or row >= len(self._track3d_lists):
            return
        match_row = self._find_row_by_key(self._current_lists, self._entry_key(self._track3d_lists[row]))
        if match_row >= 0:
            self.current_list_widget.blockSignals(True)
            self.current_list_widget.setCurrentRow(match_row)
            self.current_list_widget.blockSignals(False)

    def _match_same_key(self) -> None:
        current_row = self.current_list_widget.currentRow()
        if current_row >= 0:
            self._sync_selection_to_track3d(current_row)
            return
        track3d_row = self.track3d_list_widget.currentRow()
        if track3d_row >= 0:
            self._sync_selection_to_current(track3d_row)

    def _copy_selected_track3d_to_current(self) -> None:
        current_row = self.current_list_widget.currentRow()
        track3d_row = self.track3d_list_widget.currentRow()
        if current_row < 0 or track3d_row < 0:
            return
        self._current_lists[current_row].tso_ids = list(self._track3d_lists[track3d_row].tso_ids)
        self._refresh_lists()
        self.current_list_widget.setCurrentRow(current_row)
        self.track3d_list_widget.setCurrentRow(track3d_row)

    def _copy_all_matching_rows(self) -> None:
        track3d_by_key = {self._entry_key(entry): list(entry.tso_ids) for entry in self._track3d_lists}
        changed = False
        for entry in self._current_lists:
            replacement = track3d_by_key.get(self._entry_key(entry))
            if replacement is None or replacement == entry.tso_ids:
                continue
            entry.tso_ids = list(replacement)
            changed = True
        if changed:
            self._refresh_lists()

    def _add_selected_track3d_row(self) -> None:
        track3d_row = self.track3d_list_widget.currentRow()
        if track3d_row < 0 or track3d_row >= len(self._track3d_lists):
            return
        selected_entry = self._track3d_lists[track3d_row]
        selected_key = self._entry_key(selected_entry)
        if self._find_row_by_key(self._current_lists, selected_key) >= 0:
            QMessageBox.information(
                self,
                "Add .3D Row",
                "That ObjectList is already in the current project.",
            )
            return
        self._current_lists.append(
            Track3DObjectList(
                side=selected_entry.side,
                section=selected_entry.section,
                sub_index=selected_entry.sub_index,
                tso_ids=list(selected_entry.tso_ids),
            )
        )
        self._current_lists.sort(key=self._sort_key)
        self._refresh_lists()
        added_row = self._find_row_by_key(self._current_lists, selected_key)
        if added_row >= 0:
            self.current_list_widget.setCurrentRow(added_row)
        self.track3d_list_widget.setCurrentRow(track3d_row)

    def _add_missing_track3d_rows(self) -> None:
        existing_keys = {self._entry_key(entry) for entry in self._current_lists}
        additions = [
            Track3DObjectList(side=entry.side, section=entry.section, sub_index=entry.sub_index, tso_ids=list(entry.tso_ids))
            for entry in self._track3d_lists
            if self._entry_key(entry) not in existing_keys
        ]
        if not additions:
            return
        self._current_lists.extend(additions)
        self._current_lists.sort(key=self._sort_key)
        self._refresh_lists()

    def _delete_selected_current_row(self) -> None:
        current_row = self.current_list_widget.currentRow()
        if current_row < 0 or current_row >= len(self._current_lists):
            return
        entry = self._current_lists[current_row]
        response = QMessageBox.question(
            self,
            "Delete ObjectList",
            (
                "Delete the selected ObjectList from the current project?\n\n"
                f"{self._format_entry(entry)}"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if response != QMessageBox.Yes:
            return
        del self._current_lists[current_row]
        self._refresh_lists()
        if self.current_list_widget.count() > 0:
            self.current_list_widget.setCurrentRow(min(current_row, self.current_list_widget.count() - 1))

    def _sort_both_lists(self) -> None:
        self._current_lists.sort(key=self._sort_key)
        self._track3d_lists.sort(key=self._sort_key)
        self._refresh_lists()

    def _copy_selected_ids(self, widget: QListWidget, entries: list[Track3DObjectList]) -> None:
        row = widget.currentRow()
        if row < 0 or row >= len(entries):
            return
        text = ", ".join(f"__TSO{tso_id}" for tso_id in entries[row].tso_ids)
        QApplication.clipboard().setText(text)

    def reconciled_object_lists(self) -> list[Track3DObjectList]:
        return [
            Track3DObjectList(side=entry.side, section=entry.section, sub_index=entry.sub_index, tso_ids=list(entry.tso_ids))
            for entry in self._current_lists
        ]


class TSOVisibilityTab(QWidget):
    selectedTSOsChanged = QtCore.pyqtSignal(tuple)
    selectedTSOPillChanged = QtCore.pyqtSignal(object)
    selectedTrackSectionChanged = QtCore.pyqtSignal(object)
    selectedTSOOrderChanged = QtCore.pyqtSignal(object)
    objectListsChanged = QtCore.pyqtSignal()
    objectListsSaved = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()

        layout = QVBoxLayout(self)

        self.load_button = QPushButton("Load ObjectLists from track.3D")
        self.reconcile_button = QPushButton("Reconcile Project vs track.3D")
        self.save_to_track3d_button = QPushButton("Save ObjectLists to track.3D")
        self.export_button = QPushButton("Export ObjectLists to File")
        self.add_tso_button = QPushButton("Add selected TSO to section")
        self.delete_tso_button = QPushButton("Remove selected TSO from section")
        self.copy_prev_button = QPushButton("Copy TSOs from previous section")

        self.load_button.setToolTip(
            "Load ObjectLists from a track.3D file. This replaces the current TSO visibility data."
        )
        self.reconcile_button.setToolTip(
            "Compare current ObjectLists with another track.3D file and copy/add matching rows."
        )
        self.save_to_track3d_button.setToolTip(
            "Write the current ObjectLists back into a selected track.3D file."
        )
        self.export_button.setToolTip("Export the current ObjectLists to a standalone text file.")
        self.add_tso_button.setToolTip(
            "Add the selected TSO from the filter list to the currently selected section/sub-index."
        )
        self.delete_tso_button.setToolTip(
            "Remove the selected TSO pill from the currently selected section/sub-index."
        )
        self.copy_prev_button.setToolTip(
            "Copy the previous section's visible TSO list into the currently selected section/sub-index."
        )

        button_rows = QVBoxLayout()
        top_button_row = QHBoxLayout()
        for button in (
            self.load_button,
            self.reconcile_button,
        ):
            top_button_row.addWidget(button)
        button_rows.addLayout(top_button_row)

        bottom_button_row = QHBoxLayout()
        for button in (
            self.save_to_track3d_button,
            self.export_button,
        ):
            bottom_button_row.addWidget(button)
        button_rows.addLayout(bottom_button_row)
        layout.addLayout(button_rows)

        layout.addWidget(QLabel("Sections / Side / SubIndex"))
        self.section_list = TrackSectionListWidget()
        layout.addWidget(self.section_list, 0)

        lists_row = QHBoxLayout()
        layout.addLayout(lists_row)

        left_panel = QVBoxLayout()
        center_panel = QVBoxLayout()
        right_panel = QVBoxLayout()
        lists_row.addLayout(left_panel, 1)
        lists_row.addLayout(center_panel, 0)
        lists_row.addLayout(right_panel, 1)

        tso_filter_label = QLabel("TSO list")
        tso_filter_label.setToolTip("Check Filter to narrow sections. Select a TSO row for Add selected TSO to section.")
        left_panel.addWidget(tso_filter_label)
        self.tso_filter_list = QTableWidget()
        self.tso_filter_list.setColumnCount(2)
        self.tso_filter_list.setHorizontalHeaderLabels(["Filter", "TSO"])
        self.tso_filter_list.verticalHeader().setVisible(False)
        self.tso_filter_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tso_filter_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tso_filter_list.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tso_filter_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tso_filter_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tso_filter_list.itemChanged.connect(self._on_tso_filter_changed)
        left_panel.addWidget(self.tso_filter_list)

        center_panel.addStretch(1)
        center_panel.addWidget(self.add_tso_button)
        center_panel.addWidget(self.delete_tso_button)
        center_panel.addWidget(self.copy_prev_button)
        center_panel.addStretch(1)

        right_panel.addWidget(QLabel("Visible TSOs (drag to reorder)"))
        self.tso_list = TSOVisibilityListWidget()
        self.tso_list.setDragDropMode(QListWidget.InternalMove)
        self.tso_list.setDefaultDropAction(QtCore.Qt.MoveAction)
        self.tso_list.setStyleSheet(
            "QListWidget::item {"
            "  border: 1px solid palette(mid);"
            "  border-radius: 10px;"
            "  padding: 2px 8px;"
            "  background: palette(button);"
            "  color: palette(text);"
            "}"
            "QListWidget::item:selected {"
            "  background: #0078d4;"
            "  color: #ffffff;"
            "}"
        )
        right_panel.addWidget(self.tso_list)

        self.load_button.clicked.connect(self.load_file)
        self.add_tso_button.clicked.connect(self._on_add_tso_requested)
        self.delete_tso_button.clicked.connect(self._on_delete_tso_requested)
        self.copy_prev_button.clicked.connect(self._on_copy_from_previous_requested)
        self.reconcile_button.clicked.connect(self._on_reconcile_requested)
        self.export_button.clicked.connect(self._on_export_requested)
        self.save_to_track3d_button.clicked.connect(self._on_save_to_track3d_requested)
        self.section_list.rowSelectionChanged.connect(self._emit_selected_tsos)
        self.tso_list.orderChanged.connect(self._on_tso_order_changed)
        self.tso_list.itemClicked.connect(self._on_tso_pill_selected)

        self.object_lists = []
        self.available_tso_ids: list[int] = []
        self._tso_display_metadata: dict[int, tuple[str, str]] = {}
        self._subsection_dlong_ranges: dict[tuple[int, int], tuple[int, int | None]] = {}
        self._section_subindex_starts: dict[int, tuple[int, ...]] = {}
        self._current_track_section_count: int | None = None
        QtCore.QTimer.singleShot(0, self._resize_section_list)

    def set_current_track_section_count(self, count: int | None) -> None:
        if isinstance(count, int) and count >= 0:
            self._current_track_section_count = count
            return
        self._current_track_section_count = None

    def set_section_dlong_rows(self, rows: list[Track3DSectionDlongList]) -> None:
        ranges, subindex_starts = build_subsection_dlong_metadata(rows)
        self._subsection_dlong_ranges = ranges
        self._section_subindex_starts = subindex_starts

    def _find_object_list_index_for_current_selection(self) -> int:
        item = self.section_list.currentItem()
        if item is None:
            return -1
        mapped_index = item.data(QtCore.Qt.UserRole)
        if isinstance(mapped_index, int) and 0 <= mapped_index < len(self.object_lists):
            return mapped_index
        return -1

    def _build_tso_filter_label(self, tso_id: int) -> str:
        return self._build_tso_pill_text(tso_id)

    def _collect_all_tso_ids(self) -> list[int]:
        all_ids = {
            tso_id
            for object_list in self.object_lists
            for tso_id in object_list.tso_ids
            if tso_id >= 0
        }
        all_ids.update({tso_id for tso_id in self.available_tso_ids if tso_id >= 0})
        all_ids.update(
            {tso_id for tso_id in self._tso_display_metadata.keys() if isinstance(tso_id, int) and tso_id >= 0}
        )
        return sorted(all_ids)

    def _selected_filter_tso_ids(self) -> set[int]:
        selected: set[int] = set()
        for index in range(self.tso_filter_list.rowCount()):
            item = self.tso_filter_list.item(index, 0)
            if item is None or item.checkState() != QtCore.Qt.Checked:
                continue
            tso_id = item.data(QtCore.Qt.UserRole)
            if isinstance(tso_id, int) and tso_id >= 0:
                selected.add(tso_id)
        return selected

    def _refresh_tso_filter_list(self) -> None:
        selected_before = self._selected_filter_tso_ids()
        selected_item = self.tso_filter_list.currentItem()
        selected_tso_id_for_add = selected_item.data(QtCore.Qt.UserRole) if selected_item is not None else None
        all_ids = self._collect_all_tso_ids()
        self.tso_filter_list.blockSignals(True)
        self.tso_filter_list.clearContents()
        self.tso_filter_list.setRowCount(0)
        selected_row_for_add = -1
        self.tso_filter_list.setRowCount(len(all_ids))
        for row, tso_id in enumerate(all_ids):
            filter_item = QTableWidgetItem("")
            filter_item.setData(QtCore.Qt.UserRole, tso_id)
            filter_item.setFlags(
                QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsUserCheckable
            )
            filter_item.setCheckState(QtCore.Qt.Checked if tso_id in selected_before else QtCore.Qt.Unchecked)
            self.tso_filter_list.setItem(row, 0, filter_item)

            tso_item = QTableWidgetItem(self._build_tso_filter_label(tso_id))
            tso_item.setData(QtCore.Qt.UserRole, tso_id)
            tso_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
            self.tso_filter_list.setItem(row, 1, tso_item)
            if selected_tso_id_for_add == tso_id:
                selected_row_for_add = row
        if selected_row_for_add >= 0:
            self.tso_filter_list.setCurrentCell(selected_row_for_add, 1)
        elif self.tso_filter_list.rowCount() > 0:
            self.tso_filter_list.setCurrentCell(0, 1)
        self.tso_filter_list.blockSignals(False)

    def _on_tso_filter_changed(self, _item: QListWidgetItem) -> None:
        self.populate_table()

    def _build_tso_pill_text(self, tso_id: int) -> str:
        label = f"__TSO{tso_id}"
        filename, description = self._tso_display_metadata.get(tso_id, ("", ""))
        details: list[str] = []
        if filename:
            details.append(filename)
        if description:
            details.append(description)
        if details:
            return f"{label} ({' — '.join(details)})"
        return label

    def _make_tso_list_item(self, tso_id: int) -> QListWidgetItem:
        item = QListWidgetItem(self._build_tso_pill_text(tso_id))
        item.setData(QtCore.Qt.UserRole, tso_id)
        return item

    def _assigned_tso_ids(self) -> set[int]:
        return {
            tso_id
            for object_list in self.object_lists
            for tso_id in object_list.tso_ids
            if tso_id >= 0
        }

    def _build_add_tso_dialog_label(self, tso_id: int, assigned_ids: set[int]) -> str:
        label = self._build_tso_pill_text(tso_id)
        if tso_id not in assigned_ids:
            return f"{label} *"
        return label

    def clear_object_lists(self) -> None:
        self.object_lists = []
        self._subsection_dlong_ranges = {}
        self._section_subindex_starts = {}
        self.section_list.clear()
        self.tso_list.clear()
        self.tso_filter_list.clearContents()
        self.tso_filter_list.setRowCount(0)
        self.selectedTSOsChanged.emit(tuple())
        self.selectedTSOPillChanged.emit(None)
        self.selectedTrackSectionChanged.emit(None)
        self.selectedTSOOrderChanged.emit({})
        self.objectListsSaved.emit()

    def set_object_lists(self, object_lists: list[Track3DObjectList]) -> None:
        self.object_lists = list(object_lists)
        self._refresh_tso_filter_list()
        self.populate_table()
        self.selectedTSOsChanged.emit(tuple())
        self.selectedTSOPillChanged.emit(None)
        self.selectedTrackSectionChanged.emit(None)
        self.selectedTSOOrderChanged.emit({})
        self.objectListsSaved.emit()

    def _emit_track_section_and_order(self, row: int) -> None:
        if row < 0 or row >= len(self.object_lists):
            self.selectedTrackSectionChanged.emit(None)
            self.selectedTSOOrderChanged.emit({})
            return
        entry = self.object_lists[row]
        start_dlong, end_dlong = self._subsection_dlong_ranges.get(
            (int(entry.section), int(entry.sub_index)),
            (None, None),
        )
        self.selectedTrackSectionChanged.emit(
            {
                "section": int(entry.section),
                "sub_index": int(entry.sub_index),
                "start_dlong": start_dlong,
                "end_dlong": end_dlong,
                "subindex_count": len(self._section_subindex_starts.get(int(entry.section), tuple())),
                "subindex_starts": self._section_subindex_starts.get(int(entry.section), tuple()),
            }
        )
        order_map: dict[int, int] = {}
        for order, tso_id in enumerate(entry.tso_ids, start=1):
            if tso_id < 0:
                continue
            order_map[int(tso_id)] = order
        self.selectedTSOOrderChanged.emit(order_map)

    def serialize_object_lists(self) -> list[dict[str, object]]:
        payload: list[dict[str, object]] = []
        for entry in self.object_lists:
            payload.append(
                {
                    "side": str(entry.side),
                    "section": int(entry.section),
                    "sub_index": int(entry.sub_index),
                    "tso_ids": [int(tso_id) for tso_id in entry.tso_ids],
                }
            )
        return payload

    @staticmethod
    def _object_list_layout_signature(
        object_lists: list[Track3DObjectList],
    ) -> tuple[tuple[str, int, int], ...]:
        return tuple(
            (str(entry.side), int(entry.section), int(entry.sub_index))
            for entry in object_lists
        )

    def load_object_lists_from_payload(self, payload: object) -> None:
        if not isinstance(payload, list):
            self.clear_object_lists()
            return

        parsed_lists = []
        for raw_entry in payload:
            if not isinstance(raw_entry, dict):
                continue
            side = str(raw_entry.get("side", "")).strip().upper()
            if side not in {"L", "R"}:
                continue
            try:
                section = int(raw_entry.get("section", 0))
                sub_index = int(raw_entry.get("sub_index", 0))
            except (TypeError, ValueError):
                continue
            raw_tso_ids = raw_entry.get("tso_ids", [])
            tso_ids: list[int] = []
            if isinstance(raw_tso_ids, list):
                for tso_id in raw_tso_ids:
                    try:
                        parsed_id = int(tso_id)
                    except (TypeError, ValueError):
                        continue
                    if parsed_id >= 0:
                        tso_ids.append(parsed_id)
            parsed_lists.append(
                Track3DObjectList(
                    side=side,
                    section=section,
                    sub_index=sub_index,
                    tso_ids=tso_ids,
                )
            )

        self.set_object_lists(parsed_lists)

    def set_available_tso_ids(self, tso_ids: list[int] | tuple[int, ...]) -> None:
        self.available_tso_ids = sorted({tso_id for tso_id in tso_ids if tso_id >= 0})
        self._refresh_tso_filter_list()
        self.populate_table()

    def set_tso_display_metadata(self, metadata: dict[int, tuple[str, str]]) -> None:
        normalized: dict[int, tuple[str, str]] = {}
        for tso_id, values in metadata.items():
            if not isinstance(tso_id, int) or tso_id < 0:
                continue
            filename = ""
            description = ""
            if isinstance(values, tuple) and len(values) == 2:
                filename = str(values[0]).strip()
                description = str(values[1]).strip()
            normalized[tso_id] = (filename, description)
        self._tso_display_metadata = normalized
        self._refresh_tso_filter_list()
        self.populate_table()
        self._refresh_visible_tso_column()

    def load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open track.3D",
            "",
            "3D Files (*.3D *.3d);;All Files (*)",
        )

        if not path:
            return

        if self.object_lists:
            response = QMessageBox.warning(
                self,
                "Load track.3D",
                "Loading track.3D will overwrite the current TSO Visibility data. Continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if response != QMessageBox.Yes:
                return

        if not track3d_has_object_lists(path):
            QMessageBox.warning(
                self,
                "Load track.3D",
                "The selected track.3D file does not contain any ObjectLists.",
            )
            return

        section_rows = parse_track3d_section_dlongs(path)
        if not section_rows:
            QMessageBox.warning(
                self,
                "Load track.3D",
                "The selected track.3D file does not contain any section ObjectLists/DATA rows.",
            )
            return

        loaded_section_count = len({int(row.section) for row in section_rows})
        if (
            self._current_track_section_count is not None
            and loaded_section_count != self._current_track_section_count
        ):
            QMessageBox.warning(
                self,
                "Load track.3D",
                "The selected track.3D file has a different number of sections than the current track.\n\n"
                f"Current track sections: {self._current_track_section_count}\n"
                f"track.3D sections: {loaded_section_count}",
            )
            return

        self.object_lists = parse_track3d(path)
        self.set_section_dlong_rows(section_rows)
        self._refresh_tso_filter_list()
        if not self.available_tso_ids:
            self.available_tso_ids = sorted(
                {
                    tso_id
                    for object_list in self.object_lists
                    for tso_id in object_list.tso_ids
                    if tso_id >= 0
                }
            )

        self.populate_table()
        self.objectListsSaved.emit()

    def remap_tso_ids(self, remap: dict[int, int]) -> None:
        if not remap:
            return
        changed = False
        for object_list in self.object_lists:
            updated_ids: list[int] = []
            row_changed = False
            for tso_id in object_list.tso_ids:
                mapped = remap.get(tso_id, tso_id)
                updated_ids.append(mapped)
                if mapped != tso_id:
                    row_changed = True
            if row_changed:
                object_list.tso_ids = updated_ids
                changed = True
        if not changed:
            return
        self._emit_object_lists_changed()
        self._refresh_tso_filter_list()
        self.populate_table()

    def _emit_object_lists_changed(self) -> None:
        self.objectListsChanged.emit()

    def populate_table(self):
        current_object_index = self._find_object_list_index_for_current_selection()
        selected_tso_ids = self._selected_filter_tso_ids()
        left_section_items: list[QTableWidgetItem] = []
        right_section_items: list[QTableWidgetItem] = []
        for object_list_index, entry in enumerate(self.object_lists):
            if selected_tso_ids and not any(tso_id in selected_tso_ids for tso_id in entry.tso_ids):
                continue
            label = f"{entry.section} / {entry.sub_index}"
            item = QTableWidgetItem(label)
            item.setData(QtCore.Qt.UserRole, object_list_index)
            if str(entry.side).strip().upper() == "R":
                right_section_items.append(item)
            else:
                left_section_items.append(item)

        self.section_list.set_entries(left_section_items, right_section_items)

        if self.section_list.count() == 0:
            self.tso_list.clear()
            self.selectedTSOsChanged.emit(tuple())
            self.selectedTSOPillChanged.emit(None)
            self.selectedTrackSectionChanged.emit(None)
            self.selectedTSOOrderChanged.emit({})
            return

        preferred_row = 0
        if current_object_index >= 0:
            for row in range(self.section_list.count()):
                item = self.section_list.item(row)
                if item is None:
                    continue
                if item.data(QtCore.Qt.UserRole) == current_object_index:
                    preferred_row = row
                    break
        self.section_list.setCurrentRow(preferred_row)

    def _on_tso_order_changed(self) -> None:
        object_list_index = self._find_object_list_index_for_current_selection()
        if object_list_index < 0:
            return
        reordered_ids: list[int] = []
        for index in range(self.tso_list.count()):
            item = self.tso_list.item(index)
            if item is None:
                continue
            text = item.text().strip()
            item_tso_id = item.data(QtCore.Qt.UserRole)
            if isinstance(item_tso_id, int):
                reordered_ids.append(item_tso_id)
            elif text.startswith("__TSO"):
                try:
                    reordered_ids.append(int(text.replace("__TSO", "", 1)))
                except ValueError:
                    continue
        self.object_lists[object_list_index].tso_ids = reordered_ids
        self._emit_object_lists_changed()
        self.selectedTSOsChanged.emit(tuple(reordered_ids))
        self._emit_track_section_and_order(object_list_index)
        self.populate_table()

    def _refresh_current_tso_list(self, selected_tso_id: int | None = None) -> None:
        row = self._find_object_list_index_for_current_selection()
        self.tso_list.clear()
        if row < 0 or row >= len(self.object_lists):
            return
        selected_row = -1
        for tso_id in self.object_lists[row].tso_ids:
            self.tso_list.addItem(self._make_tso_list_item(tso_id))
            if selected_tso_id is not None and selected_row < 0 and tso_id == selected_tso_id:
                selected_row = self.tso_list.count() - 1
        if selected_row >= 0:
            self.tso_list.setCurrentRow(selected_row)
        self.tso_list.update_item_widths()

    def _emit_selected_tsos(self) -> None:
        row = self._find_object_list_index_for_current_selection()
        if row < 0 or row >= len(self.object_lists):
            self.selectedTSOsChanged.emit(tuple())
            self.selectedTSOPillChanged.emit(None)
            self.selectedTrackSectionChanged.emit(None)
            self.selectedTSOOrderChanged.emit({})
            return
        self.selectedTSOsChanged.emit(tuple(self.object_lists[row].tso_ids))
        selected_item = self.tso_list.currentItem()
        selected_tso_id = (
            selected_item.data(QtCore.Qt.UserRole)
            if selected_item is not None and isinstance(selected_item.data(QtCore.Qt.UserRole), int)
            else None
        )
        if selected_tso_id is None:
            self.selectedTSOPillChanged.emit(None)
        else:
            self.selectedTSOPillChanged.emit(selected_tso_id)
        self._emit_track_section_and_order(row)
        self._refresh_current_tso_list(selected_tso_id)

    def _on_tso_pill_selected(self, item: QListWidgetItem | None) -> None:
        row = self._find_object_list_index_for_current_selection()
        if row < 0 or row >= len(self.object_lists):
            self.selectedTSOPillChanged.emit(None)
            return
        if item is None:
            self.selectedTSOPillChanged.emit(None)
            return
        text = item.text().strip()
        item_tso_id = item.data(QtCore.Qt.UserRole)
        if isinstance(item_tso_id, int):
            tso_id = item_tso_id
        else:
            if not text.startswith("__TSO"):
                self.selectedTSOPillChanged.emit(None)
                return
            try:
                tso_id = int(text.replace("__TSO", "", 1))
            except ValueError:
                self.selectedTSOPillChanged.emit(None)
                return
        self.selectedTSOPillChanged.emit(tso_id)

    def _resize_section_list(self) -> None:
        target_height = max(140, int(self.height() * 0.25))
        self.section_list.setFixedHeight(target_height)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._resize_section_list()
        self.tso_list.update_item_widths()

    def _refresh_visible_tso_column(self) -> None:
        self.tso_list.update_item_widths()

    def _update_row_height(self, row: int, widget: TSOVisibilityListWidget) -> None:
        _ = (row, widget)

    def _on_add_tso_requested(self) -> None:
        row = self._find_object_list_index_for_current_selection()
        if row < 0 or row >= len(self.object_lists):
            return
        current_row = self.tso_filter_list.currentRow()
        if current_row < 0:
            return
        selected_filter_item = self.tso_filter_list.item(current_row, 1)
        if selected_filter_item is None:
            return
        tso_id = selected_filter_item.data(QtCore.Qt.UserRole)
        if not isinstance(tso_id, int):
            return

        selected_pill = self.tso_list.currentItem()
        insert_index = len(self.object_lists[row].tso_ids)
        if selected_pill is not None:
            selected_row = self.tso_list.row(selected_pill)
            if selected_row >= 0:
                insert_index = min(selected_row + 1, len(self.object_lists[row].tso_ids))

        self.object_lists[row].tso_ids.insert(insert_index, tso_id)
        self._emit_object_lists_changed()
        self._refresh_current_tso_list()
        item = self.tso_list.item(insert_index)
        if item is not None:
            self.tso_list.setCurrentItem(item)
        self.selectedTSOPillChanged.emit(tso_id)
        self.selectedTSOsChanged.emit(tuple(self.object_lists[row].tso_ids))
        self._emit_track_section_and_order(row)
        self.populate_table()

    def _on_delete_tso_requested(self) -> None:
        row = self._find_object_list_index_for_current_selection()
        if row < 0 or row >= len(self.object_lists):
            return
        item = self.tso_list.currentItem()
        if item is None:
            return
        item_row = self.tso_list.row(item)
        if item_row < 0:
            return
        self.tso_list.takeItem(item_row)
        if item_row < len(self.object_lists[row].tso_ids):
            del self.object_lists[row].tso_ids[item_row]
            self._emit_object_lists_changed()
        self.tso_list.update_item_widths()
        self.selectedTSOPillChanged.emit(None)
        self.selectedTSOsChanged.emit(tuple(self.object_lists[row].tso_ids))
        self._emit_track_section_and_order(row)
        self.populate_table()

    def _on_export_requested(self) -> None:
        if not self.object_lists:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export ObjectLists",
            "object_lists.txt",
            "Text Files (*.txt);;All Files (*)",
        )
        if not path:
            return

        lines: list[str] = []
        for entry in self.object_lists:
            tso_parts = ", ".join(f"__TSO{tso_id}" for tso_id in entry.tso_ids)
            lines.append(
                f"ObjectList_{entry.side}{entry.section}_{entry.sub_index}: LIST {{ {tso_parts} }};"
            )
        with open(path, "w", encoding="utf-8") as output_file:
            output_file.write("\n".join(lines) + "\n")


    def _on_save_to_track3d_requested(self) -> None:
        if not self.object_lists:
            QMessageBox.information(self, "Save ObjectLists", "No ObjectLists to save.")
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select track.3D to update",
            "",
            "3D Files (*.3D *.3d);;All Files (*)",
        )
        if not path:
            return
        if not track3d_has_object_lists(path):
            QMessageBox.warning(
                self,
                "Save ObjectLists",
                "The selected track.3D file does not contain any ObjectLists.",
            )
            return

        file_object_lists = parse_track3d(path)
        current_layout = self._object_list_layout_signature(self.object_lists)
        file_layout = self._object_list_layout_signature(file_object_lists)
        if current_layout != file_layout:
            QMessageBox.warning(
                self,
                "Save ObjectLists",
                "The selected track.3D file does not perfectly match the current app ObjectList layout.\n\n"
                "Use Reconcile .3D first so every Sections / Side / SubIndex row lines up before saving.",
            )
            return

        try:
            backup_path = save_object_lists_to_track3d(path, self.object_lists)
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Save ObjectLists",
                f"Failed to update track.3D:\n{exc}",
            )
            return

        QMessageBox.information(
            self,
            "Save ObjectLists",
            "Updated track.3D with current ObjectList rows.\n"
            f"Backup created at:\n{backup_path}",
        )
        self.objectListsSaved.emit()

    def _on_copy_from_previous_requested(self) -> None:
        row = self._find_object_list_index_for_current_selection()
        if row <= 0 or row >= len(self.object_lists):
            return

        copied_ids = list(self.object_lists[row - 1].tso_ids)
        self.object_lists[row].tso_ids = copied_ids
        self._emit_object_lists_changed()

        self._refresh_current_tso_list()

        self.selectedTSOPillChanged.emit(None)
        self.selectedTSOsChanged.emit(tuple(copied_ids))
        self._emit_track_section_and_order(row)
        self.populate_table()

    def _on_reconcile_requested(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open track.3D to reconcile",
            "",
            "3D Files (*.3D *.3d);;All Files (*)",
        )
        if not path:
            return
        if not track3d_has_object_lists(path):
            QMessageBox.warning(
                self,
                "Reconcile track.3D",
                "The selected track.3D file does not contain any ObjectLists.",
            )
            return

        dialog = TSOVisibilityReconcileDialog(self.object_lists, parse_track3d(path), self)
        if dialog.exec_() != QDialog.Accepted:
            return
        self.set_object_lists(dialog.reconciled_object_lists())
        self._emit_object_lists_changed()
