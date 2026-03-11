from PyQt5 import QtCore
from PyQt5.QtWidgets import (
    QFileDialog,
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

    def dropEvent(self, event):
        super().dropEvent(event)
        self.orderChanged.emit()


class TSOVisibilityTab(QWidget):
    selectedTSOsChanged = QtCore.pyqtSignal(tuple)

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
            tso_list.setFlow(QListWidget.LeftToRight)
            tso_list.setDragDropMode(QListWidget.InternalMove)
            tso_list.setDefaultDropAction(QtCore.Qt.MoveAction)
            tso_list.setWrapping(True)
            tso_list.setSpacing(4)
            tso_list.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            tso_list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            tso_list.setStyleSheet(
                "QListWidget::item {"
                "  border: 1px solid palette(mid);"
                "  border-radius: 10px;"
                "  padding: 2px 8px;"
                "  background: palette(button);"
                "}"
            )
            for tso_id in entry.tso_ids:
                tso_list.addItem(QListWidgetItem(f"__TSO{tso_id}"))
            tso_list.orderChanged.connect(
                lambda row_index=row, widget=tso_list: self._on_tso_order_changed(row_index, widget)
            )
            self.table.setCellWidget(row, 3, tso_list)

        self.table.resizeRowsToContents()
        self.table.resizeColumnToContents(0)
        self.table.resizeColumnToContents(1)
        self.table.resizeColumnToContents(2)

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
            return
        self.selectedTSOsChanged.emit(tuple(self.object_lists[row].tso_ids))
