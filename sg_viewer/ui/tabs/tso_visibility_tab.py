from PyQt5 import QtCore
from PyQt5.QtGui import QResizeEvent
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QMessageBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sg_viewer.io.track3d_parser import (
    Track3DObjectList,
    Track3DSectionDlongList,
    parse_track3d,
    parse_track3d_section_dlongs,
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


class TrackSectionListWidget(QListWidget):
    rowSelectionChanged = QtCore.pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.setSelectionMode(QListWidget.SingleSelection)
        self.currentRowChanged.connect(self.rowSelectionChanged.emit)


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

        lists_row = QHBoxLayout()
        layout.addLayout(lists_row)

        left_panel = QVBoxLayout()
        right_panel = QVBoxLayout()
        lists_row.addLayout(left_panel, 1)
        lists_row.addLayout(right_panel, 1)

        left_panel.addWidget(QLabel("Sections / Side / SubIndex"))
        self.section_list = TrackSectionListWidget()
        left_panel.addWidget(self.section_list)

        left_panel.addWidget(QLabel("Filter by TSO"))
        self.tso_filter_list = QListWidget()
        self.tso_filter_list.setSelectionMode(QListWidget.NoSelection)
        self.tso_filter_list.itemChanged.connect(self._on_tso_filter_changed)
        left_panel.addWidget(self.tso_filter_list)

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
            "  background: palette(light);"
            "  color: palette(text);"
            "}"
        )
        right_panel.addWidget(self.tso_list)

        self.load_button.clicked.connect(self.load_file)
        self.add_tso_button.clicked.connect(self._on_add_tso_requested)
        self.delete_tso_button.clicked.connect(self._on_delete_tso_requested)
        self.copy_prev_button.clicked.connect(self._on_copy_from_previous_requested)
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

    def set_section_dlong_rows(self, rows: list[Track3DSectionDlongList]) -> None:
        ranges: dict[tuple[int, int], tuple[int, int | None]] = {}
        subindex_starts: dict[int, list[tuple[int, int]]] = {}
        for row in rows:
            if not row.dlongs:
                continue
            section = int(row.section)
            sub_index = int(row.sub_index)
            start_dlong = int(row.dlongs[0])
            end_dlong = int(row.dlongs[-1])
            if end_dlong < start_dlong:
                start_dlong, end_dlong = end_dlong, start_dlong
            ranges[(section, sub_index)] = (start_dlong, end_dlong)
            subindex_starts.setdefault(section, []).append((sub_index, start_dlong))

        self._subsection_dlong_ranges = ranges
        self._section_subindex_starts = {
            section: tuple(start for _, start in sorted(values, key=lambda item: item[0]))
            for section, values in subindex_starts.items()
        }

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
        for index in range(self.tso_filter_list.count()):
            item = self.tso_filter_list.item(index)
            if item is None or item.checkState() != QtCore.Qt.Checked:
                continue
            tso_id = item.data(QtCore.Qt.UserRole)
            if isinstance(tso_id, int) and tso_id >= 0:
                selected.add(tso_id)
        return selected

    def _refresh_tso_filter_list(self) -> None:
        selected_before = self._selected_filter_tso_ids()
        all_ids = self._collect_all_tso_ids()
        self.tso_filter_list.blockSignals(True)
        self.tso_filter_list.clear()
        for tso_id in all_ids:
            item = QListWidgetItem(self._build_tso_filter_label(tso_id))
            item.setData(QtCore.Qt.UserRole, tso_id)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            check_state = QtCore.Qt.Checked if tso_id in selected_before else QtCore.Qt.Unchecked
            item.setCheckState(check_state)
            self.tso_filter_list.addItem(item)
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
        self.tso_filter_list.clear()
        self.selectedTSOsChanged.emit(tuple())
        self.selectedTSOPillChanged.emit(None)
        self.selectedTrackSectionChanged.emit(None)
        self.selectedTSOOrderChanged.emit({})

    def set_object_lists(self, object_lists: list[Track3DObjectList]) -> None:
        self.object_lists = list(object_lists)
        self._refresh_tso_filter_list()
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

        self.object_lists = parse_track3d(path)
        self.set_section_dlong_rows(parse_track3d_section_dlongs(path))
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

    def populate_table(self):
        current_object_index = self._find_object_list_index_for_current_selection()
        selected_tso_ids = self._selected_filter_tso_ids()
        self.section_list.clear()
        for object_list_index, entry in enumerate(self.object_lists):
            if selected_tso_ids and not any(tso_id in selected_tso_ids for tso_id in entry.tso_ids):
                continue
            label = f"{entry.side} / {entry.section} / {entry.sub_index}"
            item = QListWidgetItem(label)
            item.setData(QtCore.Qt.UserRole, object_list_index)
            self.section_list.addItem(item)

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
        self.selectedTSOsChanged.emit(tuple(reordered_ids))
        self._emit_track_section_and_order(object_list_index)
        self.populate_table()

    def _refresh_current_tso_list(self) -> None:
        row = self._find_object_list_index_for_current_selection()
        self.tso_list.clear()
        if row < 0 or row >= len(self.object_lists):
            return
        for tso_id in self.object_lists[row].tso_ids:
            self.tso_list.addItem(self._make_tso_list_item(tso_id))
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
        self.selectedTSOPillChanged.emit(None)
        self._emit_track_section_and_order(row)
        self._refresh_current_tso_list()

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

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.tso_list.update_item_widths()

    def _refresh_visible_tso_column(self) -> None:
        self.tso_list.update_item_widths()

    def _update_row_height(self, row: int, widget: TSOVisibilityListWidget) -> None:
        _ = (row, widget)

    def _on_add_tso_requested(self) -> None:
        row = self._find_object_list_index_for_current_selection()
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
        dialog.resize(500, 420)
        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.addWidget(QLabel("Choose a TSO to add:"))
        dialog_layout.addWidget(
            QLabel("* indicates this TSO is not assigned to any visibility row yet.")
        )

        list_widget = QListWidget(dialog)
        list_widget.setSelectionMode(QListWidget.SingleSelection)
        list_widget.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        assigned_ids = self._assigned_tso_ids()
        for tso_id in available_ids:
            item = QListWidgetItem(self._build_add_tso_dialog_label(tso_id, assigned_ids))
            item.setData(QtCore.Qt.UserRole, tso_id)
            list_widget.addItem(item)
        if list_widget.count() > 0:
            list_widget.setCurrentRow(0)
        list_widget.itemDoubleClicked.connect(lambda _item: dialog.accept())
        dialog_layout.addWidget(list_widget)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        dialog_layout.addWidget(buttons)

        if dialog.exec_() != QDialog.Accepted:
            return
        selected_items = list_widget.selectedItems()
        if not selected_items:
            return
        tso_id = selected_items[0].data(QtCore.Qt.UserRole)
        if not isinstance(tso_id, int):
            return

        self.object_lists[row].tso_ids.append(tso_id)
        self._refresh_current_tso_list()
        item = self.tso_list.item(self.tso_list.count() - 1)
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
        row = self._find_object_list_index_for_current_selection()
        if row <= 0 or row >= len(self.object_lists):
            return

        copied_ids = list(self.object_lists[row - 1].tso_ids)
        self.object_lists[row].tso_ids = copied_ids

        self._refresh_current_tso_list()

        self.selectedTSOPillChanged.emit(None)
        self.selectedTSOsChanged.emit(tuple(copied_ids))
        self._emit_track_section_and_order(row)
        self.populate_table()
