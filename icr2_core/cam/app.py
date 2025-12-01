# PyQt version of the ICR2 Camera Editor
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
                             QTableWidgetItem, QPushButton, QFileDialog, QLabel, QTabWidget, QMessageBox)
import csv
import sys
import os
from to_csv import scr_to_csv, cam_to_csv
from from_csv import csv_to_scr, csv_to_cam

class CameraEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ICR2 Camera Editor (PyQt Edition)")
        self.resize(1000, 600)

        self.filename_scr = None
        self.filename_cam = None

        self.tabs = QTabWidget()
        self.scr_table = QTableWidget()
        self.cam_table = QTableWidget()

        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        layout = QVBoxLayout()

        btn_row = QHBoxLayout()
        open_btn = QPushButton("Open SCR and CAM")
        save_scr_btn = QPushButton("Save SCR")
        save_cam_btn = QPushButton("Save CAM")
        open_btn.clicked.connect(self.open_files)
        save_scr_btn.clicked.connect(self.save_scr)
        save_cam_btn.clicked.connect(self.save_cam)
        btn_row.addWidget(open_btn)
        btn_row.addWidget(save_scr_btn)
        btn_row.addWidget(save_cam_btn)

        self.tabs.addTab(self.scr_table, "SCR Triggers")
        self.tabs.addTab(self.cam_table, "CAM Definitions")

        layout.addLayout(btn_row)
        layout.addWidget(self.tabs)
        central_widget.setLayout(layout)
        self.setCentralWidget(central_widget)

    def open_files(self):
        scr_path, _ = QFileDialog.getOpenFileName(self, "Open SCR File", "", "SCR Files (*.scr)")
        cam_path, _ = QFileDialog.getOpenFileName(self, "Open CAM File", "", "CAM Files (*.cam)")
        if scr_path and cam_path:
            self.filename_scr = scr_path
            self.filename_cam = cam_path

            scr_to_csv(scr_path, "temp_scr.csv")
            cam_to_csv(cam_path, "temp_cam.csv")

            self.load_scr_table("temp_scr.csv")
            self.load_cam_table("temp_cam.csv")

    def load_scr_table(self, csv_file):
        with open(csv_file, newline='') as f:
            reader = csv.reader(f)
            lines = list(reader)[3:]  # skip headers
            self.scr_table.setRowCount(len(lines))
            self.scr_table.setColumnCount(5)
            self.scr_table.setHorizontalHeaderLabels(["View", "Mark", "Cam ID", "Start DLONG", "End DLONG"])
            for i, row in enumerate(lines):
                for j in range(5):
                    self.scr_table.setItem(i, j, QTableWidgetItem(row[j]))

    def load_cam_table(self, csv_file):
        with open(csv_file, newline='') as f:
            reader = csv.reader(f)
            rows = []
            current_type = None
            for row in reader:
                if not row:
                    continue
                if row[0].startswith("Number of Type"):
                    current_type = row[0].split()[3]
                    continue
                if row[0].startswith("ID"):
                    continue
                rows.append([current_type] + row)

            self.cam_table.setRowCount(len(rows))
            self.cam_table.setColumnCount(14)
            headers = ["Type", "Index"] + [f"Field{i}" for i in range(1, 13)]
            self.cam_table.setHorizontalHeaderLabels(headers)
            for i, row in enumerate(rows):
                for j in range(len(row)):
                    self.cam_table.setItem(i, j, QTableWidgetItem(row[j]))

    def save_scr(self):
        if self.filename_scr:
            csv_to_scr("temp_scr.csv", self.filename_scr)
            QMessageBox.information(self, "Saved", f"SCR file saved to {self.filename_scr}")

    def save_cam(self):
        if self.filename_cam:
            csv_to_cam("temp_cam.csv", self.filename_cam)
            QMessageBox.information(self, "Saved", f"CAM file saved to {self.filename_cam}")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    editor = CameraEditor()
    editor.show()
    sys.exit(app.exec_())
