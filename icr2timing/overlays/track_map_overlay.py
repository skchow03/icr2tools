from PyQt5 import QtWidgets, QtCore, QtGui
import os

import logging
log = logging.getLogger(__name__)

from overlays.base_overlay import BaseOverlay
from icr2_core.model import RaceState
from icr2_core.trk.track_loader import load_trk_from_folder
from icr2_core.trk.trk_utils import getxyz, get_cline_pos
from core.config import Config



class TrackMapOverlay(QtWidgets.QWidget):




    def __init__(self):
        super().__init__()
        flags = (
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.Window
            | QtCore.Qt.WindowStaysOnTopHint
        )
        # flags = QtCore.Qt.FramelessWindowHint | QtCore.Qt.Window
        self.setWindowFlags(flags)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)

        self.resize(500, 400)
        self.move(200, 200)

        self._scale_factor = 0.5   # default scaling
        self._show_numbers = True  # default: show numbers
        self._color_by_lp = False  # default: not using LP colors
        self._bubble_size = 4  # default AI bubble radius
        self._line_thickness = 2  # default track line thickness (in pixels)


        self._last_state: RaceState | None = None
        self._drag_pos: QtCore.QPoint | None = None
        self.trk = None
        self.cline = []
        self._sampled_pts = []

        self.installEventFilter(self)

    # -----------------------------
    # Helpers
    # -----------------------------
    def _load_track(self, track_name: str):
        exe_path = Config().game_exe
        if not exe_path:
            raise RuntimeError("Game EXE not set in settings.ini")

        exe_dir = os.path.dirname(exe_path)
        track_folder = os.path.join(exe_dir, "TRACKS", track_name.lower())
        log.info(f"[TrackMapOverlay] Loading track from: {track_folder}")

        self.trk = load_trk_from_folder(track_folder)
        self.cline = get_cline_pos(self.trk)

        self._sample_centerline()
        self._autosize_window()

    def _sample_centerline(self, step: int = 10000):
        if not self.trk:
            self._sampled_pts = []
            return

        pts = []
        dlong = 0
        while dlong <= self.trk.trklength:
            x, y, _ = getxyz(self.trk, dlong, 0, self.cline)
            pts.append((x, y))
            dlong += step
        if pts and pts[0] != pts[-1]:
            pts.append(pts[0])

        self._sampled_pts = pts
        log.info(f"[TrackMapOverlay] Sampled {len(self._sampled_pts)} points")

    def _autosize_window(self, margin: int = 20):
        if not self._sampled_pts:
            return

        xs = [p[0] for p in self._sampled_pts]
        ys = [p[1] for p in self._sampled_pts]
        track_w = max(xs) - min(xs)
        track_h = max(ys) - min(ys)

        if track_w <= 0 or track_h <= 0:
            return

        aspect = track_w / track_h
        base_size = 600  # base target size before scaling

        if aspect >= 1:
            window_w = base_size
            window_h = base_size / aspect
        else:
            window_w = base_size * aspect
            window_h = base_size

        # apply scale factor
        window_w = int(window_w * self._scale_factor) + margin * 2
        window_h = int(window_h * self._scale_factor) + margin * 2

        self.resize(window_w, window_h)
        #print(f"[TrackMapOverlay] Resized overlay to {window_w} x {window_h} (aspect {aspect:.2f}, scale {self._scale_factor})")


    # -----------------------------
    # BaseOverlay API
    # -----------------------------
    def widget(self):
        return self

    def on_state_updated(self, state: RaceState, update_bests: bool = True):
        try:
            current_name = getattr(state, "track_name", "") or ""
            # Ignore empty or None names
            if not current_name.strip():
                return

            # Only reload when the track name really changes
            if getattr(self, "_loaded_track_name", None) != current_name:
                self._loaded_track_name = current_name
                exe_path = Config().game_exe
                exe_dir = os.path.dirname(exe_path) if exe_path else "(none)"
                log.info(f"[TrackMapOverlay] Loading track from: {exe_dir}\\TRACKS\\{current_name.lower()}")
                self._load_track(current_name)
                log.info(f"[TrackMapOverlay] Loaded track: {current_name}")

            self._last_state = state
            self.update()

        except Exception as e:
            if getattr(self, "_last_error_msg", None) != str(e):
                log.error(f"[TrackMapOverlay] Track load failed: {e}")
                self._last_error_msg = str(e)
            self.trk = None
            self._sampled_pts = []


    def on_error(self, msg: str):
        """Handle memory read or updater errors."""
        self._last_state = None
        # Optionally show a single visible warning once
        if getattr(self, "_last_error_msg", None) != msg:
            import logging
            log = logging.getLogger(__name__)
            log.error(f"[TrackMapOverlay] on_error: {msg}")
            self._last_error_msg = msg
        self.update()


    # -----------------------------
    # Painting
    # -----------------------------
    def paintEvent(self, event):

        LP_COLORS = {
            0: ("Race", QtGui.QColor.fromHsv(0, 0, 255)),       # white
            1: ("Pass 1", QtGui.QColor.fromHsv(120, 255, 255)), # green
            2: ("Pass 2", QtGui.QColor.fromHsv(240, 255, 255)), # blue
            3: ("Pit", QtGui.QColor.fromHsv(60, 255, 255)),     # yellow
            4: ("Pace", QtGui.QColor.fromHsv(300, 255, 255)),   # magenta
        }

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 128))

        if not self._sampled_pts:
            painter.setPen(QtGui.QPen(QtGui.QColor("red"), 2))
            painter.drawText(10, 20, "Track map not loaded")
            return

        xs = [p[0] for p in self._sampled_pts]
        ys = [p[1] for p in self._sampled_pts]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        w, h = self.width(), self.height()
        margin = 20

        track_w = max_x - min_x
        track_h = max_y - min_y

        sx = (w - margin * 2) / track_w
        sy = (h - margin * 2) / track_h
        scale = min(sx, sy)

        x_offset = (w - track_w * scale) / 2 - min_x * scale
        y_offset = (h - track_h * scale) / 2 - min_y * scale

        def map_point(x, y):
            px = x * scale + x_offset
            py = y * scale + y_offset
            return px, h - py

        # --- Draw track path ---
        painter.setPen(QtGui.QPen(QtGui.QColor("white"), self._line_thickness))
        path = QtGui.QPainterPath()
        for i, (x, y) in enumerate(self._sampled_pts):
            px, py = map_point(x, y)
            if i == 0:
                path.moveTo(px, py)
            else:
                path.lineTo(px, py)
        painter.drawPath(path)

        # --- Draw cars ---
        if self._last_state and self.trk:
            cfg = Config()
            player_idx = cfg.player_index

            if self._show_numbers:
                painter.setFont(QtGui.QFont("Arial", 8, QtGui.QFont.Bold))

            for idx, car_state in self._last_state.car_states.items():
                try:
                    x, y, _ = getxyz(self.trk, car_state.dlong, car_state.dlat, self.cline)
                    px, py = map_point(x, y)

                    # Determine LP line index (if available)
                    lp = getattr(car_state, "current_lp", 0) or 0

                    if self._color_by_lp:
                        label, color = LP_COLORS.get(lp, ("Other", QtGui.QColor.fromHsv((lp * 40) % 360, 255, 255)))
                        radius = self._bubble_size
                    elif idx == player_idx:
                        color = QtGui.QColor("lime")
                        radius = self._bubble_size * 2
                    else:
                        color = QtGui.QColor("cyan")
                        radius = self._bubble_size


                    # Draw bubble
                    painter.setBrush(QtGui.QBrush(color))
                    painter.setPen(QtGui.QPen(QtGui.QColor("black")))
                    painter.drawEllipse(QtCore.QPointF(px, py), radius, radius)

                    # Draw number (if enabled)
                    if self._show_numbers:
                        driver = self._last_state.drivers.get(idx)
                        if driver and driver.car_number is not None:
                            num = str(driver.car_number)
                            tx = int(px + radius + 2)
                            ty = int(py - radius - 2)
                            painter.setPen(QtGui.QPen(QtGui.QColor("white")))
                            painter.drawText(tx, ty, num)

                except Exception as e:
                    log.error(f"[TrackMapOverlay] ERROR drawing car {idx}: {e}")
                    continue

        if self._color_by_lp:
            painter.setFont(QtGui.QFont("Arial", 8))
            x0, y0 = 10, 10
            line_height = 14
            for i, (lp_idx, (label, color)) in enumerate(LP_COLORS.items()):
                painter.setBrush(color)
                painter.setPen(QtGui.QPen(QtGui.QColor("black")))
                painter.drawRect(x0, y0 + i * line_height, 12, 12)

                painter.setPen(QtGui.QPen(QtGui.QColor("white")))
                painter.drawText(x0 + 18, y0 + 10 + i * line_height - 2, label)




    def set_scale_factor(self, f: float):
        self._scale_factor = f
        self._autosize_window()
        self.update()

    def set_show_numbers(self, enabled: bool):
        self._show_numbers = enabled
        self.update()

    def set_color_by_lp(self, enabled: bool):
        self._color_by_lp = enabled
        self.update()

    def set_bubble_size(self, size: int):
        self._bubble_size = max(1, size)  # avoid 0
        self.update()


    def set_line_thickness(self, thickness: int):
        """Set the width of the drawn track line."""
        self._line_thickness = max(1, thickness)
        self.update()

    # -----------------------------
    # Dragging
    # -----------------------------
    def eventFilter(self, source, event):
        if (
            event.type() == QtCore.QEvent.MouseButtonPress
            and event.button() == QtCore.Qt.LeftButton
        ):
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
            return True
        elif event.type() == QtCore.QEvent.MouseMove and (
            event.buttons() & QtCore.Qt.LeftButton
        ):
            if self._drag_pos is not None:
                self.move(event.globalPos() - self._drag_pos)
                event.accept()
                return True
        elif event.type() == QtCore.QEvent.MouseButtonRelease:
            self._drag_pos = None
            event.accept()
            return True
        return super().eventFilter(source, event)


BaseOverlay.register(TrackMapOverlay)
