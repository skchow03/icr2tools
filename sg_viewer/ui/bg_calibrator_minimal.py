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
from pathlib import Path
from typing import Callable, Optional, Tuple, List
import json
import argparse

from PyQt5 import QtCore, QtGui, QtWidgets, QtNetwork

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

def vec_add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def vec_sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def vec_dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def vec_scale(v, s):
    return (v[0] * s, v[1] * s)


def mat2_mul_vec(R, v):
    return (
        R[0][0] * v[0] + R[0][1] * v[1],
        R[1][0] * v[0] + R[1][1] * v[1],
    )


def similarity_fit(P, Q):
    n = len(P)
    if n != len(Q) or n < 2:
        raise ValueError("similarity_fit requires at least two paired points")

    p_mean = (sum(p[0] for p in P) / n, sum(p[1] for p in P) / n)
    q_mean = (sum(q[0] for q in Q) / n, sum(q[1] for q in Q) / n)

    a = 0.0
    b = 0.0
    p_norm_sq = 0.0
    for p, q in zip(P, Q):
        px, py = vec_sub(p, p_mean)
        qx, qy = vec_sub(q, q_mean)
        a += px * qx + py * qy
        b += px * qy - py * qx
        p_norm_sq += px * px + py * py

    if p_norm_sq <= 0.0:
        return 0.0, ((1.0, 0.0), (0.0, 1.0))

    theta = math.atan2(b, a)
    c = math.cos(theta)
    s_theta = math.sin(theta)
    R = ((c, -s_theta), (s_theta, c))

    s = math.hypot(a, b) / p_norm_sq
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
        self._adding_point = False

    def start_point_add(self):
        self._adding_point = True
        self.setDragMode(QtWidgets.QGraphicsView.NoDrag)
        self.setCursor(QtCore.Qt.ArrowCursor)

    def finish_point_add(self):
        self._adding_point = False
        self.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
        self.setCursor(QtCore.Qt.OpenHandCursor)

    def wheelEvent(self, e):
        factor = 1.25 if e.angleDelta().y() > 0 else 1 / 1.25
        self.scale(factor, factor)

    def mouseMoveEvent(self, e):
        if not self._adding_point:
            self.setCursor(QtCore.Qt.OpenHandCursor)
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton and self._adding_point:
            sp = self.mapToScene(e.pos())
            self.pointAdded.emit(float(sp.x()), float(sp.y()))
            self.finish_point_add()
            e.accept()
            return
        super().mousePressEvent(e)

# -------------------------------------------------
# Main Window
# -------------------------------------------------

class Calibrator(QtWidgets.QMainWindow):
    calibrationSubmitted = QtCore.pyqtSignal(dict)

    def __init__(
        self,
        initial_image_path: Optional[str] = None,
        send_endpoint: Optional[str] = None,
        send_callback: Optional[Callable[[dict], None]] = None,
        parent: Optional[QtWidgets.QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("ICR2 Background Calibrator")
        self.resize(1200, 800)

        self.scene = QtWidgets.QGraphicsScene(self)
        self.view = ImageView(self.scene)
        self.view.pointAdded.connect(self.add_point)

        self.bg_item = None
        self.points: List[CalPoint] = []
        self.image_size: Optional[Tuple[int, int]] = None
        self.current_image_path: Optional[str] = None
        self._suppress_table_edit = False
        self._send_endpoint = send_endpoint
        self._send_callback = send_callback

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
        add_point_btn = QtWidgets.QPushButton("Add calibration point")
        add_point_btn.clicked.connect(self.view.start_point_add)
        save_btn = QtWidgets.QPushButton("Save Settings…")
        save_btn.clicked.connect(self.save_settings)
        load_btn = QtWidgets.QPushButton("Load Settings…")
        load_btn.clicked.connect(self.load_settings)
        send_btn = QtWidgets.QPushButton("Send values to SG Viewer")
        send_btn.clicked.connect(self.send_values_to_main_app)
        send_btn.setEnabled(bool(send_endpoint or send_callback))
        if not send_endpoint and send_callback is None:
            send_btn.setToolTip("Launch this calibrator from SG Viewer to enable sending")

        right = QtWidgets.QVBoxLayout()
        right.addWidget(open_btn)
        right.addWidget(add_point_btn)
        right.addWidget(save_btn)
        right.addWidget(load_btn)
        right.addWidget(send_btn)
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

        if initial_image_path:
            self._load_image(initial_image_path)

    # -------------------------------------------------

    def open_image(self):
        fn, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open Image", "", "Images (*.png *.jpg *.bmp *.tif)"
        )
        if not fn:
            return

        self._load_image(fn)

    def _load_image(self, fn: str) -> bool:
        pm = QtGui.QPixmap(fn)
        if pm.isNull():
            QtWidgets.QMessageBox.warning(self, "Open Image", "Failed to load image")
            return False

        self.scene.clear()
        self.bg_item = self.scene.addPixmap(pm)
        self.scene.setSceneRect(0.0, 0.0, float(pm.width()), float(pm.height()))
        self.view.fitInView(self.scene.sceneRect(), QtCore.Qt.KeepAspectRatio)

        self.image_size = (pm.width(), pm.height())
        self.points.clear()
        self.table.setRowCount(0)
        self.out_scale.clear()
        self.out_ul.clear()
        self.current_image_path = fn

        return True

    def add_point(self, x, y):
        self._add_point(x, y)

    def _add_point(self, x, y, lat=None, lon=None):
        pen = QtGui.QPen(QtGui.QColor("cyan"))
        pen.setWidthF(1.0)
        size = 6.0

        h = self.scene.addLine(x - size, y, x + size, y, pen)
        v = self.scene.addLine(x, y - size, x, y + size, pen)

        p = CalPoint(px=x, py=y, lat=lat, lon=lon, items=[h, v])
        self.points.append(p)

        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(row + 1)))
        self.table.setItem(row, 1, QtWidgets.QTableWidgetItem(f"{x:.6f}"))
        self.table.setItem(row, 2, QtWidgets.QTableWidgetItem(f"{y:.6f}"))
        latlon_text = "" if lat is None or lon is None else f"{lat:.6f}, {lon:.6f}"

        self._suppress_table_edit = True
        self.table.setItem(row, 3, QtWidgets.QTableWidgetItem(latlon_text))
        self._suppress_table_edit = False

    def on_table_edit(self, item):
        if self._suppress_table_edit:
            return
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

        P = [(p.px - cx, cy - p.py) for p in usable]

        Qm = [
            latlon_to_local_meters(p.lat, p.lon, lat0, lon0)
            for p in usable
        ]
        unit_scale = meters_to_units(1.0)
        Q = [vec_scale(qm, unit_scale) for qm in Qm]

        s, R = similarity_fit(P, Q)

        # Upper-left pixel (0,0) relative to center
        ul_vec = (-cx, +cy)
        world_ul = vec_scale(mat2_mul_vec(R, ul_vec), s)

        self.out_scale.setText(f"{s:.9f}")
        self.out_ul.setText(f"{world_ul[0]:.3f}, {world_ul[1]:.3f}")

    # -------------------------------------------------

    def save_settings(self):
        if self.image_size is None or not self.current_image_path:
            QtWidgets.QMessageBox.warning(self, "Save Settings", "Load an image first")
            return

        self.recompute()

        scale = self._parse_float(self.out_scale.text())
        upper_left = self._parse_pair(self.out_ul.text())

        settings = {
            "image_path": self.current_image_path,
            "points": [
                {
                    "px": p.px,
                    "py": p.py,
                    "lat": p.lat,
                    "lon": p.lon,
                }
                for p in self.points
            ],
            "units_per_pixel": scale,
            "upper_left": upper_left,
        }

        fn, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Settings", "", "Calibration files (*.json)"
        )
        if not fn:
            return

        try:
            with open(fn, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2)
        except OSError as e:
            QtWidgets.QMessageBox.warning(
                self, "Save Settings", f"Failed to save file:\n{e}"
            )

    def load_settings(self):
        fn, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load Settings", "", "Calibration files (*.json)"
        )
        if not fn:
            return

        try:
            with open(fn, "r", encoding="utf-8") as f:
                data = json.load(f)
        except OSError as e:
            QtWidgets.QMessageBox.warning(
                self, "Load Settings", f"Failed to read file:\n{e}"
            )
            return

        image_path = data.get("image_path")
        if not image_path:
            QtWidgets.QMessageBox.warning(
                self, "Load Settings", "No image path found in settings"
            )
            return

        img_path = Path(image_path)
        if not img_path.is_absolute():
            img_path = Path(fn).parent / img_path

        if not self._load_image(str(img_path)):
            return

        points = data.get("points", [])
        for p in points:
            self._add_point(p.get("px"), p.get("py"), p.get("lat"), p.get("lon"))

        saved_scale = data.get("units_per_pixel")
        saved_ul = data.get("upper_left")

        self.recompute()

        if saved_scale is not None:
            self.out_scale.setText(f"{saved_scale:.9f}")
        if isinstance(saved_ul, (list, tuple)) and len(saved_ul) == 2:
            self.out_ul.setText(f"{saved_ul[0]:.3f}, {saved_ul[1]:.3f}")

    def _parse_float(self, text: str) -> Optional[float]:
        try:
            return float(text)
        except (TypeError, ValueError):
            return None

    def _parse_pair(self, text: str) -> Optional[Tuple[float, float]]:
        try:
            x_str, y_str = text.split(",")
            return float(x_str.strip()), float(y_str.strip())
        except Exception:
            return None

    def send_values_to_main_app(self):
        if not self._send_endpoint and self._send_callback is None:
            QtWidgets.QMessageBox.information(
                self,
                "Send Disabled",
                "No SG Viewer endpoint was provided. Open this calibrator from SG Viewer to send values.",
            )
            return

        self.recompute()
        scale = self._parse_float(self.out_scale.text())
        upper_left = self._parse_pair(self.out_ul.text())
        if scale is None or upper_left is None:
            QtWidgets.QMessageBox.warning(
                self,
                "Missing Calibration",
                "Compute a valid calibration before sending values.",
            )
            return

        payload = {
            "units_per_pixel": scale,
            "upper_left": [upper_left[0], upper_left[1]],
        }
        if self.current_image_path:
            payload["image_path"] = self.current_image_path

        if self._send_callback is not None:
            self._send_callback(payload)
            self.calibrationSubmitted.emit(payload)
            QtWidgets.QMessageBox.information(
                self,
                "Applied",
                "Applied calibration values in SG Viewer.",
            )
            return

        socket = QtNetwork.QLocalSocket(self)
        socket.connectToServer(self._send_endpoint)
        if not socket.waitForConnected(1500):
            QtWidgets.QMessageBox.warning(
                self,
                "Send Failed",
                "Could not connect to SG Viewer."
            )
            return

        encoded_payload = json.dumps(payload).encode("utf-8")
        bytes_enqueued = socket.write(encoded_payload)
        if bytes_enqueued < 0:
            QtWidgets.QMessageBox.warning(
                self,
                "Send Failed",
                "Failed to send calibration values to SG Viewer.",
            )
            socket.disconnectFromServer()
            return

        socket.flush()
        if not socket.waitForBytesWritten(1500) and socket.bytesToWrite() > 0:
            QtWidgets.QMessageBox.warning(
                self,
                "Send Failed",
                "Failed to send calibration values to SG Viewer.",
            )
            socket.disconnectFromServer()
            return

        socket.disconnectFromServer()
        QtWidgets.QMessageBox.information(
            self,
            "Sent",
            "Sent calibration values to SG Viewer.",
        )

# -------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image_path", nargs="?", default=None)
    parser.add_argument("--send-endpoint", dest="send_endpoint", default=None)
    args = parser.parse_args()

    app = QtWidgets.QApplication([])
    win = Calibrator(
        initial_image_path=args.image_path,
        send_endpoint=args.send_endpoint,
    )
    win.show()
    app.exec_()

if __name__ == "__main__":
    main()
