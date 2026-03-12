from PyQt5 import QtCore
from PyQt5.QtGui import QResizeEvent
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QMessageBox,
    QHeaderView,
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
    parse_track3d,
    save_object_lists_to_track3d,
)


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

    def dropEvent(self, event):
        super().dropEvent(event)
        self.orderChanged.emit()
        self.contentHeightChanged.emit()


class TSOVisibilityTab(QWidget):
    selectedTSOsChanged = QtCore.pyqtSignal(tuple)
    selectedTSOPillChanged = QtCore.pyqtSignal(object)
    selectedTrackSectionChanged = QtCore.pyqtSignal(object)
    selectedTSOOrderChanged = QtCore.pyqtSignal(object)

    def __init__(self):
        super().__init__()

        layout = QVBoxLayout(self)

        self.load_button = QPushButton("Load track.3D")
        self.add_tso_button = QPushButton("Add TSO")
        self.delete_tso_button = QPushButton("Delete TSO")
        self.copy_prev_button = QPushButton("Copy from Previous")
        self.export_button = QPushButton("Export ObjectLists")
        self.save_to_track3d_button = QPushButton("Save ObjectLists to track.3D")

        button_row = QHBoxLayout()
        button_row.addWidget(self.load_button)
        button_row.addWidget(self.add_tso_button)
        button_row.addWidget(self.delete_tso_button)
        button_row.addWidget(self.copy_prev_button)
        button_row.addWidget(self.export_button)
        button_row.addWidget(self.save_to_track3d_button)
        layout.addLayout(button_row)

        self.table = QTableWidget()
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        layout.addWidget(self.table)

        self.load_button.clicked.connect(self.load_file)
        self.add_tso_button.clicked.connect(self._on_add_tso_requested)
        self.delete_tso_button.clicked.connect(self._on_delete_tso_requested)
        self.copy_prev_button.clicked.connect(self._on_copy_from_previous_requested)
        self.export_button.clicked.connect(self._on_export_requested)
        self.save_to_track3d_button.clicked.connect(self._on_save_to_track3d_requested)
        self.table.itemSelectionChanged.connect(self._emit_selected_tsos)
        self.table.horizontalHeader().sectionResized.connect(self._on_column_resized)

        self.object_lists = []
        self.available_tso_ids: list[int] = []
        self._tso_display_metadata: dict[int, tuple[str, str]] = {}

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

    def clear_object_lists(self) -> None:
        self.object_lists = []
        self.table.clearContents()
        self.table.setRowCount(0)
        self.selectedTSOsChanged.emit(tuple())
        self.selectedTSOPillChanged.emit(None)
        self.selectedTrackSectionChanged.emit(None)
        self.selectedTSOOrderChanged.emit({})

    def set_object_lists(self, object_lists: list[Track3DObjectList]) -> None:
        self.object_lists = list(object_lists)
        self.populate_table()
        self.selectedTSOsChanged.emit(tuple())
        self.selectedTSOPillChanged.emit(None)
        self.selectedTrackSectionChanged.emit(None)
        self.selectedTSOOrderChanged.emit({})

    def _emit_track_section_and_order(self, row: int) -> None:
        if row < 0 or row >= len(self.object_lists):
            self.selectedTrackSectionChanged.emit(None)
            self.selectedTSOOrderChanged.emit({})
            return
        entry = self.object_lists[row]
        self.selectedTrackSectionChanged.emit(int(entry.section))
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

        self.object_lists = parse_track3d(path)
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

    def populate_table(self):
        self.table.setRowCount(len(self.object_lists))
        self.table.setColumnCount(4)

        self.table.setHorizontalHeaderLabels(["Side", "Section", "SubIndex", "Visible TSOs"])

        for row, entry in enumerate(self.object_lists):
            self.table.setItem(row, 0, QTableWidgetItem(entry.side))
            self.table.setItem(row, 1, QTableWidgetItem(str(entry.section)))
            self.table.setItem(row, 2, QTableWidgetItem(str(entry.sub_index)))

            tso_list = TSOVisibilityListWidget()
            tso_list.setDragDropMode(QListWidget.InternalMove)
            tso_list.setDefaultDropAction(QtCore.Qt.MoveAction)
            tso_list.setStyleSheet(
                "QListWidget::item {"
                "  border: 1px solid palette(mid);"
                "  border-radius: 10px;"
                "  padding: 2px 8px;"
                "  background: palette(button);"
                "  color: palette(text);"
                "}"
                "QListWidget::item:selected {"
                "  background: palette(light);"
                "  color: palette(text);"
                "}"
            )
            for tso_id in entry.tso_ids:
                tso_list.addItem(self._make_tso_list_item(tso_id))
            tso_list.orderChanged.connect(
                lambda row_index=row, widget=tso_list: self._on_tso_order_changed(row_index, widget)
            )
            tso_list.contentHeightChanged.connect(
                lambda row_index=row, widget=tso_list: self._update_row_height(row_index, widget)
            )
            tso_list.itemClicked.connect(
                lambda item, row_index=row: self._on_tso_pill_selected(row_index, item)
            )
            self.table.setCellWidget(row, 3, tso_list)
            tso_list.update_item_widths()
            self._update_row_height(row, tso_list)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)

    def _on_tso_order_changed(self, row: int, widget: QListWidget) -> None:
        if row < 0 or row >= len(self.object_lists):
            return
        reordered_ids: list[int] = []
        for index in range(widget.count()):
            item = widget.item(index)
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
        self.object_lists[row].tso_ids = reordered_ids
        if self.table.currentRow() == row:
            self.selectedTSOsChanged.emit(tuple(reordered_ids))
            self._emit_track_section_and_order(row)

    def _emit_selected_tsos(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.object_lists):
            self.selectedTSOsChanged.emit(tuple())
            self.selectedTSOPillChanged.emit(None)
            self.selectedTrackSectionChanged.emit(None)
            self.selectedTSOOrderChanged.emit({})
            return
        self.selectedTSOsChanged.emit(tuple(self.object_lists[row].tso_ids))
        self.selectedTSOPillChanged.emit(None)
        self._emit_track_section_and_order(row)

    def _on_tso_pill_selected(self, row: int, item: QListWidgetItem | None) -> None:
        if row < 0 or row >= len(self.object_lists):
            self.selectedTSOPillChanged.emit(None)
            return
        self.table.selectRow(row)
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

    def _on_column_resized(self, column: int, _old_size: int, _new_size: int) -> None:
        if column != 3:
            return
        self._refresh_visible_tso_column()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._refresh_visible_tso_column()

    def _refresh_visible_tso_column(self) -> None:
        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, 3)
            if not isinstance(widget, TSOVisibilityListWidget):
                continue
            widget.update_item_widths()
            self._update_row_height(row, widget)

    def _update_row_height(self, row: int, widget: TSOVisibilityListWidget) -> None:
        if row < 0 or row >= self.table.rowCount():
            return
        self.table.setRowHeight(row, max(widget.content_height(), 24))

    def _on_add_tso_requested(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.object_lists):
            return
        available_ids = self.available_tso_ids or sorted(
            {
                tso_id
                for object_list in self.object_lists
                for tso_id in object_list.tso_ids
                if tso_id >= 0
            }
        )
        if not available_ids:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Add TSO")
        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.addWidget(QLabel("Choose a TSO to add:"))
        combo = QComboBox(dialog)
        for tso_id in available_ids:
            combo.addItem(self._build_tso_pill_text(tso_id), tso_id)
        dialog_layout.addWidget(combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        dialog_layout.addWidget(buttons)

        if dialog.exec_() != QDialog.Accepted:
            return
        tso_id = combo.currentData()
        if not isinstance(tso_id, int):
            return

        self.object_lists[row].tso_ids.append(tso_id)
        widget = self.table.cellWidget(row, 3)
        if isinstance(widget, TSOVisibilityListWidget):
            item = self._make_tso_list_item(tso_id)
            widget.addItem(item)
            widget.setCurrentItem(item)
            widget.update_item_widths()
            self._update_row_height(row, widget)
        self.selectedTSOPillChanged.emit(tso_id)
        self.selectedTSOsChanged.emit(tuple(self.object_lists[row].tso_ids))
        self._emit_track_section_and_order(row)

    def _on_delete_tso_requested(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.object_lists):
            return
        widget = self.table.cellWidget(row, 3)
        if not isinstance(widget, TSOVisibilityListWidget):
            return
        item = widget.currentItem()
        if item is None:
            return
        item_row = widget.row(item)
        if item_row < 0:
            return
        widget.takeItem(item_row)
        if item_row < len(self.object_lists[row].tso_ids):
            del self.object_lists[row].tso_ids[item_row]
        widget.update_item_widths()
        self._update_row_height(row, widget)
        self.selectedTSOPillChanged.emit(None)
        self.selectedTSOsChanged.emit(tuple(self.object_lists[row].tso_ids))
        self._emit_track_section_and_order(row)

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

    def _on_copy_from_previous_requested(self) -> None:
        row = self.table.currentRow()
        if row <= 0 or row >= len(self.object_lists):
            return

        copied_ids = list(self.object_lists[row - 1].tso_ids)
        self.object_lists[row].tso_ids = copied_ids

        widget = self.table.cellWidget(row, 3)
        if isinstance(widget, TSOVisibilityListWidget):
            widget.clear()
            for tso_id in copied_ids:
                widget.addItem(self._make_tso_list_item(tso_id))
            widget.update_item_widths()
            self._update_row_height(row, widget)

        self.selectedTSOPillChanged.emit(None)
        self.selectedTSOsChanged.emit(tuple(copied_ids))
        self._emit_track_section_and_order(row)
