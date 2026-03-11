from PyQt5 import QtCore
from PyQt5.QtGui import QResizeEvent
from PyQt5.QtWidgets import (
    QFileDialog,
    QHeaderView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sg_viewer.io.track3d_parser import parse_track3d


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

    def __init__(self):
        super().__init__()

        layout = QVBoxLayout(self)

        self.load_button = QPushButton("Load track.3D")
        layout.addWidget(self.load_button)

        self.table = QTableWidget()
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        layout.addWidget(self.table)

        self.load_button.clicked.connect(self.load_file)
        self.table.itemSelectionChanged.connect(self._emit_selected_tsos)
        self.table.horizontalHeader().sectionResized.connect(self._on_column_resized)

        self.object_lists = []

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
                tso_list.addItem(QListWidgetItem(f"__TSO{tso_id}"))
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
            if text.startswith("__TSO"):
                try:
                    reordered_ids.append(int(text.replace("__TSO", "", 1)))
                except ValueError:
                    continue
        self.object_lists[row].tso_ids = reordered_ids
        if self.table.currentRow() == row:
            self.selectedTSOsChanged.emit(tuple(reordered_ids))

    def _emit_selected_tsos(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.object_lists):
            self.selectedTSOsChanged.emit(tuple())
            self.selectedTSOPillChanged.emit(None)
            return
        self.selectedTSOsChanged.emit(tuple(self.object_lists[row].tso_ids))
        self.selectedTSOPillChanged.emit(None)

    def _on_tso_pill_selected(self, row: int, item: QListWidgetItem | None) -> None:
        if row < 0 or row >= len(self.object_lists):
            self.selectedTSOPillChanged.emit(None)
            return
        self.table.selectRow(row)
        if item is None:
            self.selectedTSOPillChanged.emit(None)
            return
        text = item.text().strip()
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
