from PyQt5.QtWidgets import (
    QFileDialog,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sg_viewer.io.track3d_parser import parse_track3d


class TSOVisibilityTab(QWidget):
    def __init__(self):
        super().__init__()

        layout = QVBoxLayout(self)

        self.load_button = QPushButton("Load track.3D")
        layout.addWidget(self.load_button)

        self.table = QTableWidget()
        layout.addWidget(self.table)

        self.load_button.clicked.connect(self.load_file)

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

        self.table.setHorizontalHeaderLabels(["Side", "Section", "SubIndex", "TSO Count"])

        for row, entry in enumerate(self.object_lists):
            self.table.setItem(row, 0, QTableWidgetItem(entry.side))
            self.table.setItem(row, 1, QTableWidgetItem(str(entry.section)))
            self.table.setItem(row, 2, QTableWidgetItem(str(entry.sub_index)))
            self.table.setItem(row, 3, QTableWidgetItem(str(len(entry.tso_ids))))
