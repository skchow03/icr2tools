from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from typing import List, Sequence, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2timing.overlays.base_overlay import BaseOverlay
from icr2_core.model import RaceState
from icr2_core.trk.track_loader import load_trk_from_folder
from icr2_core.trk.trk_utils import getxyz, get_cline_pos, color_from_ground_type
from icr2timing.core.config import Config

log = logging.getLogger(__name__)


@dataclass
class SurfaceStrip:
    """Represents a single ground f-section rendered as a polygon."""
    points: Sequence[Tuple[float, float]]
    ground_type: int

    def bounds(self) -> Tuple[float, float, float, float]:
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return min(xs), max(xs), min(ys), max(ys)


class ExperimentalTrackSurfaceOverlay(QtWidgets.QWidget):
    """Visualises TRK ground f-sections as filled polygons (cached)."""

    LP_COLORS = {
        0: ("Race", QtGui.QColor.fromHsv(0, 0, 255)),
        1: ("Pass 1", QtGui.QColor.fromHsv(120, 255, 255)),
        2: ("Pass 2", QtGui.QColor.fromHsv(240, 255, 255)),
        3: ("Pit", QtGui.QColor.fromHsv(60, 255, 255)),
        4: ("Pace", QtGui.QColor.fromHsv(300, 255, 255)),
    }

    def __init__(self):
        super().__init__()

        flags = (
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.Window
            | QtCore.Qt.WindowStaysOnTopHint
        )
        self.setWindowFlags(flags)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)

        self.resize(600, 500)
        self.move(250, 250)

        self._scale_factor = 0.5
        self._margin = 24
        self._show_numbers = True
        self._color_by_lp = False
        self._bubble_size = 4

        self._last_state: RaceState | None = None
        self._drag_pos: QtCore.QPoint | None = None

        self.trk = None
        self.cline: List[Tuple[float, float]] = []
        self._surface_mesh: List[SurfaceStrip] = []
        self._bounds: Tuple[float, float, float, float] | None = None

        # Cached pixmap to avoid repainting thousands of polygons every frame
        self._cached_surface_pixmap: QtGui.QPixmap | None = None
        self._pixmap_size: QtCore.QSize | None = None

        self.installEventFilter(self)

    # ------------------------------------------------------------------
    # Track loading & preprocessing
    # ------------------------------------------------------------------
    def _load_track(self, track_name: str) -> None:
        exe_path = Config().game_exe
        if not exe_path:
            raise RuntimeError("Game EXE not set in settings.ini")

        exe_dir = os.path.dirname(exe_path)
        track_folder = os.path.join(exe_dir, "TRACKS", track_name.lower())
        log.info("[ExperimentalTrackSurfaceOverlay] Loading track from: %s", track_folder)

        self.trk = load_trk_from_folder(track_folder)
        self.cline = get_cline_pos(self.trk)

        self._surface_mesh = self._build_surface_mesh()
        self._bounds = self._compute_bounds()
        self._cached_surface_pixmap = None  # invalidate cache
        self._autosize_window()

    def _build_surface_mesh(self) -> List[SurfaceStrip]:
        if not self.trk:
            return []

        strips: List[SurfaceStrip] = []
        for sect_idx, sect in enumerate(self.trk.sects):
            if sect.ground_fsects <= 0:
                continue

            num_subsects = (
                1 if sect.type == 1 else max(1, round(sect.length / 60000))
            )
            strips.extend(
                self._build_section_quads(
                    sect_idx,
                    sect.start_dlong,
                    sect.start_dlong + sect.length,
                    num_subsects=num_subsects,
                )
            )

        return strips

    def _build_section_quads(
        self,
        sect_idx: int,
        start_dlong: float,
        end_dlong: float,
        num_subsects: int,
    ) -> List[SurfaceStrip]:
        if not self.trk:
            return []

        sect = self.trk.sects[sect_idx]
        if sect.ground_fsects <= 0:
            return []

        cline = self.cline
        strips: List[SurfaceStrip] = []

        left_boundary_start = sect.bound_dlat_start[sect.num_bounds - 1]
        left_boundary_end = sect.bound_dlat_end[sect.num_bounds - 1]
        subsection_length = (end_dlong - start_dlong) / max(1, num_subsects)
        left_increment = (left_boundary_end - left_boundary_start) / max(1, num_subsects)

        for sub_idx in range(num_subsects):
            sub_start_dlong = start_dlong + subsection_length * sub_idx
            sub_end_dlong = (
                end_dlong if sub_idx == num_subsects - 1
                else start_dlong + subsection_length * (sub_idx + 1)
            )
            left_start = left_boundary_start + left_increment * sub_idx
            left_end = left_boundary_start + left_increment * (sub_idx + 1)

            for ground_idx in range(sect.ground_fsects - 1, -1, -1):
                right_start_total = sect.ground_dlat_start[ground_idx]
                right_end_total = sect.ground_dlat_end[ground_idx]
                right_span = right_end_total - right_start_total

                right_start = right_start_total + right_span * (sub_idx / num_subsects)
                right_end = right_start_total + right_span * ((sub_idx + 1) / num_subsects)

                polygon = self._quad_polygon(
                    sub_start_dlong,
                    sub_end_dlong,
                    left_start,
                    left_end,
                    right_start,
                    right_end,
                    cline,
                )

                if self._polygon_area(polygon) <= 1e-3:
                    continue

                strips.append(
                    SurfaceStrip(
                        points=polygon,
                        ground_type=sect.ground_type[ground_idx],
                    )
                )

                left_start = right_start
                left_end = right_end

        return strips

    def _quad_polygon(
        self,
        start_dlong: float,
        end_dlong: float,
        left_start: float,
        left_end: float,
        right_start: float,
        right_end: float,
        cline: Sequence[Tuple[float, float]],
    ) -> List[Tuple[float, float]]:
        if not self.trk:
            return []

        ls_x, ls_y, _ = getxyz(self.trk, start_dlong, left_start, cline)
        le_x, le_y, _ = getxyz(self.trk, end_dlong, left_end, cline)
        rs_x, rs_y, _ = getxyz(self.trk, start_dlong, right_start, cline)
        re_x, re_y, _ = getxyz(self.trk, end_dlong, right_end, cline)
        return [(ls_x, ls_y), (le_x, le_y), (re_x, re_y), (rs_x, rs_y)]

    @staticmethod
    def _polygon_area(points: Sequence[Tuple[float, float]]) -> float:
        if len(points) < 3:
            return 0.0
        area = 0.0
        for idx, (x1, y1) in enumerate(points):
            x2, y2 = points[(idx + 1) % len(points)]
            area += x1 * y2 - x2 * y1
        return abs(area) * 0.5

    def _compute_bounds(self) -> Tuple[float, float, float, float] | None:
        points: List[Tuple[float, float]] = []
        for strip in self._surface_mesh:
            points.extend(strip.points)
        if not points:
            return None
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return min(xs), max(xs), min(ys), max(ys)

    def _autosize_window(self) -> None:
        if not self._bounds:
            return
        min_x, max_x, min_y, max_y = self._bounds
        track_w = max_x - min_x
        track_h = max_y - min_y
        if track_w <= 0 or track_h <= 0:
            return

        aspect = track_w / track_h if track_h else 1
        base_size = 600
        if aspect >= 1:
            window_w = base_size
            window_h = base_size / aspect
        else:
            window_w = base_size * aspect
            window_h = base_size
        window_w = int(window_w * self._scale_factor) + self._margin * 2
        window_h = int(window_h * self._scale_factor) + self._margin * 2
        self.resize(window_w, window_h)

    # ------------------------------------------------------------------
    # BaseOverlay API
    # ------------------------------------------------------------------
    def widget(self):
        return self

    def on_state_updated(self, state: RaceState, update_bests: bool = True) -> None:
        try:
            current_name = getattr(state, "track_name", "") or ""
            if not current_name.strip():
                return

            if getattr(self, "_loaded_track_name", None) != current_name:
                self._loaded_track_name = current_name
                self._load_track(current_name)
                log.info("[ExperimentalTrackSurfaceOverlay] Loaded track: %s", current_name)

            self._last_state = state
            self.update()
        except Exception as exc:
            log.error("[ExperimentalTrackSurfaceOverlay] Track load failed: %s", exc)
            self.trk = None
            self._surface_mesh = []
            self._bounds = None
            self._cached_surface_pixmap = None
            self.update()

    def on_error(self, msg: str) -> None:
        self._last_state = None
        log.error("[ExperimentalTrackSurfaceOverlay] on_error: %s", msg)
        self.update()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------
    def _map_point(self, x: float, y: float, scale: float, offsets: Tuple[float, float]) -> QtCore.QPointF:
        px = x * scale + offsets[0]
        py = y * scale + offsets[1]
        return QtCore.QPointF(px, self.height() - py)

    def _compute_transform(self) -> Tuple[float, Tuple[float, float]] | None:
        if not self._bounds:
            return None
        min_x, max_x, min_y, max_y = self._bounds
        track_w = max_x - min_x
        track_h = max_y - min_y
        if track_w <= 0 or track_h <= 0:
            return None

        w, h = self.width(), self.height()
        scale_x = (w - self._margin * 2) / track_w
        scale_y = (h - self._margin * 2) / track_h
        scale = min(scale_x, scale_y)
        x_offset = (w - track_w * scale) / 2 - min_x * scale
        y_offset = (h - track_h * scale) / 2 - min_y * scale
        return scale, (x_offset, y_offset)

    def _render_surface_to_pixmap(self) -> QtGui.QPixmap:
        """Render the static ground polygons into a pixmap (cached)."""
        pixmap = QtGui.QPixmap(self.size())
        pixmap.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        transform = self._compute_transform()
        if not transform:
            return pixmap
        scale, offsets = transform
        for strip in self._surface_mesh:
            base_color = self._color_for_ground(strip.ground_type)
            fill = QtGui.QColor(base_color)
            fill.setAlpha(180)
            outline = base_color.darker(125)
            poly = QtGui.QPolygonF([self._map_point(x, y, scale, offsets) for x, y in strip.points])
            painter.setBrush(QtGui.QBrush(fill))
            painter.setPen(QtGui.QPen(outline, 1))
            painter.drawPolygon(poly)
        painter.end()
        return pixmap

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 160))

        if not self._surface_mesh or not self._bounds:
            painter.setPen(QtGui.QPen(QtGui.QColor("red"), 2))
            painter.drawText(12, 24, "Surface map not available")
            return

        if self._cached_surface_pixmap is None or self._pixmap_size != self.size():
            self._cached_surface_pixmap = self._render_surface_to_pixmap()
            self._pixmap_size = self.size()

        painter.drawPixmap(0, 0, self._cached_surface_pixmap)

        transform = self._compute_transform()
        if transform:
            self._draw_cars(painter, *transform)
        if self._color_by_lp:
            self._draw_lp_legend(painter)

    def _color_for_ground(self, ground_type: int) -> QtGui.QColor:
        color_name = color_from_ground_type(ground_type)
        return QtGui.QColor(color_name)

    def _draw_cars(self, painter: QtGui.QPainter, scale: float, offsets: Tuple[float, float]) -> None:
        if not self._last_state or not self.trk:
            return
        cfg = Config()
        player_idx = cfg.player_index
        if self._show_numbers:
            painter.setFont(QtGui.QFont("Arial", 8, QtGui.QFont.Bold))

        for idx, car_state in self._last_state.car_states.items():
            try:
                x, y, _ = getxyz(self.trk, car_state.dlong, car_state.dlat, self.cline)
                pt = self._map_point(x, y, scale, offsets)
                lp = getattr(car_state, "current_lp", 0) or 0
                if self._color_by_lp:
                    _, color = self.LP_COLORS.get(lp, ("Other", QtGui.QColor.fromHsv((lp * 40) % 360, 255, 255)))
                    radius = self._bubble_size
                elif idx == player_idx:
                    color = QtGui.QColor("lime")
                    radius = self._bubble_size * 2
                else:
                    color = QtGui.QColor("cyan")
                    radius = self._bubble_size
                painter.setBrush(QtGui.QBrush(color))
                painter.setPen(QtGui.QPen(QtGui.QColor("black")))
                painter.drawEllipse(pt, radius, radius)
                if self._show_numbers:
                    driver = self._last_state.drivers.get(idx)
                    if driver and driver.car_number is not None:
                        painter.setPen(QtGui.QPen(QtGui.QColor("white")))
                        painter.drawText(int(pt.x() + radius + 2), int(pt.y() - radius - 2), str(driver.car_number))
            except Exception as exc:
                log.error("[ExperimentalTrackSurfaceOverlay] ERROR drawing car %s: %s", idx, exc)

    def _draw_lp_legend(self, painter: QtGui.QPainter) -> None:
        painter.setFont(QtGui.QFont("Arial", 8))
        x0, y0, line_height = 10, 10, 14
        for i, (label, color) in enumerate(self.LP_COLORS.values()):
            painter.setBrush(color)
            painter.setPen(QtGui.QPen(QtGui.QColor("black")))
            painter.drawRect(x0, y0 + i * line_height, 12, 12)
            painter.setPen(QtGui.QPen(QtGui.QColor("white")))
            painter.drawText(x0 + 18, y0 + 10 + i * line_height - 2, label)

    # ------------------------------------------------------------------
    # Public setters
    # ------------------------------------------------------------------
    def set_scale_factor(self, factor: float) -> None:
        self._scale_factor = max(0.1, min(3.0, factor))
        self._autosize_window()
        self._cached_surface_pixmap = None
        self.update()

    def set_show_numbers(self, enabled: bool) -> None:
        self._show_numbers = enabled
        self.update()

    def set_color_by_lp(self, enabled: bool) -> None:
        self._color_by_lp = enabled
        self.update()

    def set_bubble_size(self, size: int) -> None:
        self._bubble_size = max(1, size)
        self.update()

    # ------------------------------------------------------------------
    # Dragging
    # ------------------------------------------------------------------
    def eventFilter(self, source, event):
        if event.type() == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
            return True
        elif event.type() == QtCore.QEvent.MouseMove and (event.buttons() & QtCore.Qt.LeftButton):
            if self._drag_pos is not None:
                self.move(event.globalPos() - self._drag_pos)
                event.accept()
                return True
        elif event.type() == QtCore.QEvent.MouseButtonRelease:
            self._drag_pos = None
            event.accept()
            return True
        return super().eventFilter(source, event)


BaseOverlay.register(ExperimentalTrackSurfaceOverlay)
