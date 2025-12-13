#!/usr/bin/env python3
"""
ICR2 Background Image Calibrator (minimal, precise)

Outputs ONLY:
- units_per_pixel (1 unit = 1/500 inch)
- world X,Y at image upper-left pixel (0,0)

Calibration:
- Works with 2 points minimum
- Refines automatically with more points

World math:
- World origin = image center
- X = -(px - cx)
- Y = +(cy - py)
- multiplied by units_per_pixel
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple, List

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

# -------------------------------------------------
# Constants
# -------------------------------------------------

ICR2_UNITS_PER_INCH = 500.0
INCHES_PER_METER = 39.37007874015748

# -------------------------------------------------
# Geodesy
# -------------------------------------------------

def _geodesy_backend():
    try:
        import pyproj  # noqa
        return "pyproj"
    except Exception:
        return "fallback"

_BACKEND = _geodesy_backend()

if _BACKEND == "pyproj":
    import pyproj

    def latlon_to_local_meters(lat, lon, lat0, lon0):
        crs_wgs84 = pyproj.CRS.from_epsg(4326)
        crs_enu = pyproj.CRS.from_proj4(
            f"+proj=aeqd +lat_0={lat0} +lon_0={lon0} +datum=WGS84 +units=m"
        )
        transformer = pyproj.Transformer.from_crs(
            crs_wgs84, crs_enu, always_xy=True
        )
        return transformer.transform(lon, lat)
else:
    EARTH_RADIUS_M = 6_371_000.0

    def latlon_to_local_meters(lat, lon, lat0, lon0):
        lat = math.radians(lat)
        lon = math.radians(lon)
        lat0 = math.radians(lat0)
        lon0 = math.radians(lon0)
        return (
            EARTH_RADIUS_M * math.cos(lat0) * (lon - lon0),
            EARTH_RADIUS_M * (lat - lat0),
        )

def meters_to_units(m):
    return m * INCHES_PER_METER * ICR2_UNITS_PER_INCH

# -------------------------------------------------
# Math
# -------------------------------------------------

def similarity_fit(P, Q):
    p_mean = P.mean(axis=0)
    q_mean = Q.mean(axis=0)
    P0 = P - p_mean
    Q0 = Q - q_mean

    H = P0.T @ Q0
    U, S, Vt = np.linalg.svd(H)
    R = Vt.T @ U.T
    if np.linalg.det(R) < 0:
        Vt[-1] *= -1
        R = Vt.T @ U.T

    s = S.sum() / (P0 * P0).sum()
    return s, R

# -------------------------------------------------
# Data
# -------------------------------------------------

@dataclass
class CalPoint:
    px: float
    py: float
    lat: Optional[float] = None
    lon: Optional[float] = None
    items: List[QtWidgets.QGraphicsItem] | None = None

# -------------------------------------------------
# Image View
# -------------------------------------------------

class ImageView(QtWidgets.QGraphicsView):
    pointAdded = QtCore.pyqtSignal(float, float)

    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHints(
            QtGui.QPainter.Antialiasing |
            QtGui.QPainter.SmoothPixmapTransform
        )
        self.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
        self.setCursor(QtCore.Qt.OpenHandCursor)

    def wheelEvent(self, e):
        factor = 1.25 if e.angleDelta().y() > 0 else 1 / 1.25
        self.scale(factor, factor)

    def mouseMoveEvent(self, e):
        self.setCursor(
            QtCore.Qt.CrossCursor
            if e.modifiers() & QtCore.Qt.ControlModifier
            else QtCore.Qt.OpenHandCursor
        )
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton and e.modifiers() & QtCore.Qt.ControlModifier:
            sp = self.mapToScene(e.pos())
            self.pointAdded.emit(float(sp.x()), float(sp.y()))
            e.accept()
            return
        super().mousePressEvent(e)

# -------------------------------------------------
# Main Window
# -------------------------------------------------

class Calibrator(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ICR2 Background Calibrator")
        self.resize(1200, 800)

        self.scene = QtWidgets.QGraphicsScene(self)
        self.view = ImageView(self.scene)
        self.view.pointAdded.connect(self.add_point)

        self.bg_item = None
        self.points: List[CalPoint] = []
        self.image_size: Optional[Tuple[int, int]] = None

        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["#", "px", "py", "lat, lon"])
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.itemChanged.connect(self.on_table_edit)

        self.out_scale = QtWidgets.QLineEdit(readOnly=True)
        self.out_ul = QtWidgets.QLineEdit(readOnly=True)

        open_btn = QtWidgets.QPushButton("Open Image…")
        open_btn.clicked.connect(self.open_image)

        right = QtWidgets.QVBoxLayout()
        right.addWidget(open_btn)
        right.addWidget(self.table)
        right.addWidget(QtWidgets.QLabel("500ths per pixel"))
        right.addWidget(self.out_scale)
        right.addWidget(QtWidgets.QLabel("World X,Y at image upper-left (0,0)"))
        right.addWidget(self.out_ul)
        right.addStretch()

        right_w = QtWidgets.QWidget()
        right_w.setLayout(right)

        splitter = QtWidgets.QSplitter()
        splitter.addWidget(self.view)
        splitter.addWidget(right_w)
        splitter.setStretchFactor(0, 3)
        self.setCentralWidget(splitter)

    # -------------------------------------------------

    def open_image(self):
        fn, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open Image", "", "Images (*.png *.jpg *.bmp *.tif)"
        )
        if not fn:
            return

        pm = QtGui.QPixmap(fn)
        self.scene.clear()
        self.bg_item = self.scene.addPixmap(pm)
        self.scene.setSceneRect(0.0, 0.0, float(pm.width()), float(pm.height()))
        self.view.fitInView(self.scene.sceneRect(), QtCore.Qt.KeepAspectRatio)

        self.image_size = (pm.width(), pm.height())
        self.points.clear()
        self.table.setRowCount(0)
        self.out_scale.clear()
        self.out_ul.clear()

    def add_point(self, x, y):
        pen = QtGui.QPen(QtGui.QColor("cyan"))
        pen.setWidthF(1.0)
        size = 6.0

        h = self.scene.addLine(x - size, y, x + size, y, pen)
        v = self.scene.addLine(x, y - size, x, y + size, pen)

        p = CalPoint(px=x, py=y, items=[h, v])
        self.points.append(p)

        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(row + 1)))
        self.table.setItem(row, 1, QtWidgets.QTableWidgetItem(f"{x:.6f}"))
        self.table.setItem(row, 2, QtWidgets.QTableWidgetItem(f"{y:.6f}"))
        self.table.setItem(row, 3, QtWidgets.QTableWidgetItem(""))

    def on_table_edit(self, item):
        if item.column() != 3:
            return

        r = item.row()
        if r >= len(self.points):
            return

        try:
            lat, lon = [float(v.strip()) for v in item.text().split(",")]
        except Exception:
            return

        self.points[r].lat = lat
        self.points[r].lon = lon
        self.recompute()

    # -------------------------------------------------

    def recompute(self):
        usable = [p for p in self.points if p.lat is not None and p.lon is not None]
        if len(usable) < 2 or self.image_size is None:
            return

        lat0, lon0 = usable[0].lat, usable[0].lon

        # Pixel deltas from image center, Y-up
        w, h = self.image_size
        cx = (w - 1) / 2.0
        cy = (h - 1) / 2.0

        P = np.array([[p.px - cx, cy - p.py] for p in usable])

        Qm = np.array([
            latlon_to_local_meters(p.lat, p.lon, lat0, lon0)
            for p in usable
        ])
        Q = meters_to_units(1.0) * Qm

        s, R = similarity_fit(P, Q)

        # Upper-left pixel (0,0) relative to center
        ul_vec = np.array([-cx, +cy])
        world_ul = s * (R @ ul_vec)

        self.out_scale.setText(f"{s:.9f}")
        self.out_ul.setText(f"{world_ul[0]:.3f}, {world_ul[1]:.3f}")

# -------------------------------------------------

def main():
    app = QtWidgets.QApplication([])
    win = Calibrator()
    win.show()
    app.exec_()

if __name__ == "__main__":
    main()
