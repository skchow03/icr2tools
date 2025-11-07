from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from typing import List, Sequence, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

from overlays.base_overlay import BaseOverlay
from icr2_core.model import RaceState
from icr2_core.trk.track_loader import load_trk_from_folder
from icr2_core.trk.trk_utils import getxyz, get_cline_pos, color_from_ground_type
from core.config import Config

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
    """Visualises TRK ground f-sections as filled polygons.

    The widget mirrors the behaviour of :class:`TrackMapOverlay`, but instead of
    rendering only the sampled centreline it expands every ground f-section into
    a polygon.  Each polygon is coloured by its ground type, allowing a quick
    inspection of asphalt, concrete, grass, gravel and other surfaces.
    """

    LEGEND_LABELS = {
        6: "Grass",
        14: "Dry grass",
        22: "Dirt",
        30: "Sand",
        38: "Concrete",
        46: "Asphalt",
        54: "Paint",
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

        self._last_state: RaceState | None = None
        self._drag_pos: QtCore.QPoint | None = None

        self.trk = None
        self.cline: List[Tuple[float, float]] = []
        self._centerline_points: List[Tuple[float, float]] = []
        self._surface_mesh: List[SurfaceStrip] = []
        self._bounds: Tuple[float, float, float, float] | None = None

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
        log.info(
            "[ExperimentalTrackSurfaceOverlay] Loading track from: %s",
            track_folder,
        )

        self.trk = load_trk_from_folder(track_folder)
        self.cline = get_cline_pos(self.trk)

        self._centerline_points = self._sample_centerline()
        self._surface_mesh = self._build_surface_mesh()
        self._bounds = self._compute_bounds()
        self._autosize_window()

    def _sample_centerline(self, step: int = 10000) -> List[Tuple[float, float]]:
        if not self.trk:
            return []

        pts: List[Tuple[float, float]] = []
        dlong = 0
        while dlong <= self.trk.trklength:
            x, y, _ = getxyz(self.trk, dlong, 0, self.cline)
            pts.append((x, y))
            dlong += step
        if pts and pts[0] != pts[-1]:
            pts.append(pts[0])
        return pts

    def _build_surface_mesh(self) -> List[SurfaceStrip]:
        if not self.trk:
            return []

        strips: List[SurfaceStrip] = []
        for sect_idx, sect in enumerate(self.trk.sects):
            if sect.ground_fsects <= 0:
                continue

            if sect.type == 1:
                start_dlong = sect.start_dlong
                end_dlong = sect.start_dlong + sect.length
                strips.extend(
                    self._build_section_quads(
                        sect_idx,
                        start_dlong,
                        end_dlong,
                        num_subsects=1,
                    )
                )
            else:
                num_subsects = max(1, round(sect.length / 60000))
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
        """Generate quadrilateral strips for a section or subsection.

        The implementation mirrors the original ``trk23d`` tool which produced
        OBJ meshes via ``csv2obj``: each ground f-section is represented by a
        quad whose corners are sampled with :func:`getxyz` at the subsection
        bounds.  Curves are split into smaller slices to maintain fidelity.
        """

        if not self.trk:
            return []

        sect = self.trk.sects[sect_idx]
        if sect.ground_fsects <= 0:
            return []

        cline = self.cline
        strips: List[SurfaceStrip] = []

        # Pre-compute DLAT steps for the outermost boundary which acts as the
        # left edge of the first quad within each subsection.
        left_boundary_start = sect.bound_dlat_start[sect.num_bounds - 1]
        left_boundary_end = sect.bound_dlat_end[sect.num_bounds - 1]

        # Guard against zero-length sections which could happen on malformed
        # tracks.  The TRK data is integral so we rely on integer arithmetic
        # when possible to avoid accumulation errors.
        if num_subsects <= 0:
            num_subsects = 1

        subsection_length = (end_dlong - start_dlong) / num_subsects
        left_increment = (left_boundary_end - left_boundary_start) / num_subsects

        for sub_idx in range(num_subsects):
            sub_start_dlong = start_dlong + subsection_length * sub_idx
            # Ensure the final slice terminates exactly at the section end to
            # match the behaviour in ``trk23d``.
            if sub_idx == num_subsects - 1:
                sub_end_dlong = end_dlong
            else:
                sub_end_dlong = start_dlong + subsection_length * (sub_idx + 1)

            left_start = left_boundary_start + left_increment * sub_idx
            left_end = left_boundary_start + left_increment * (sub_idx + 1)

            for ground_idx in range(sect.ground_fsects - 1, -1, -1):
                right_start_total = sect.ground_dlat_start[ground_idx]
                right_end_total = sect.ground_dlat_end[ground_idx]
                right_span = right_end_total - right_start_total

                # Interpolate the ground surface DLATs for this subsection.
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

                # Skip degenerate quads that collapse into a line.
                if self._polygon_area(polygon) <= 1e-3:
                    continue

                strips.append(
                    SurfaceStrip(
                        points=polygon,
                        ground_type=sect.ground_type[ground_idx],
                    )
                )

                # The right edge of the current quad becomes the left edge of
                # the next quad in this subsection, replicating ``trk23d``.
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

        # Ensure winding order is consistent (counter-clockwise) for rendering.
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
        points.extend(self._centerline_points)

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
                log.info(
                    "[ExperimentalTrackSurfaceOverlay] Loaded track: %s",
                    current_name,
                )

            self._last_state = state
            self.update()
        except Exception as exc:  # pragma: no cover - defensive logging
            if getattr(self, "_last_error_msg", None) != str(exc):
                log.error(
                    "[ExperimentalTrackSurfaceOverlay] Track load failed: %s",
                    exc,
                )
                self._last_error_msg = str(exc)
            self.trk = None
            self._surface_mesh = []
            self._centerline_points = []
            self._bounds = None
            self.update()

    def on_error(self, msg: str) -> None:
        self._last_state = None
        if getattr(self, "_last_error_msg", None) != msg:
            log.error("[ExperimentalTrackSurfaceOverlay] on_error: %s", msg)
            self._last_error_msg = msg
        self.update()

    # ------------------------------------------------------------------
    # Painting helpers
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
        scale_x = (w - self._margin * 2) / track_w if track_w else 1
        scale_y = (h - self._margin * 2) / track_h if track_h else 1
        scale = min(scale_x, scale_y)

        x_offset = (w - track_w * scale) / 2 - min_x * scale
        y_offset = (h - track_h * scale) / 2 - min_y * scale
        return scale, (x_offset, y_offset)

    def paintEvent(self, event):  # noqa: D401 - Qt override
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 160))

        transform = self._compute_transform()
        if transform is None or not self._surface_mesh:
            painter.setPen(QtGui.QPen(QtGui.QColor("red"), 2))
            painter.drawText(12, 24, "Surface map not available")
            return

        scale, offsets = transform

        # Draw surface strips
        for strip in self._surface_mesh:
            color_name = color_from_ground_type(strip.ground_type) or "#808080"
            base_color = QtGui.QColor(color_name)
            fill_color = QtGui.QColor(base_color)
            fill_color.setAlpha(180)

            outline = QtGui.QColor(base_color)
            outline = outline.darker(125)

            polygon = QtGui.QPolygonF(
                [self._map_point(x, y, scale, offsets) for x, y in strip.points]
            )

            painter.setBrush(QtGui.QBrush(fill_color))
            painter.setPen(QtGui.QPen(outline, 1.5))
            painter.drawPolygon(polygon)

        # Overlay the sampled centreline
        if self._centerline_points:
            pen = QtGui.QPen(QtGui.QColor("white"), 1.5)
            pen.setStyle(QtCore.Qt.DashLine)
            painter.setPen(pen)
            path = QtGui.QPainterPath()
            for i, (x, y) in enumerate(self._centerline_points):
                pt = self._map_point(x, y, scale, offsets)
                if i == 0:
                    path.moveTo(pt)
                else:
                    path.lineTo(pt)
            painter.drawPath(path)

        self._draw_legend(painter)

    def _draw_legend(self, painter: QtGui.QPainter) -> None:
        used_types = sorted({strip.ground_type for strip in self._surface_mesh})
        if not used_types:
            return

        font = QtGui.QFont("Arial", 8)
        painter.setFont(font)
        line_height = 16
        box_size = 12
        margin = 10
        x = margin
        y = margin

        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor(0, 0, 0, 160))
        legend_height = line_height * len(used_types) + 10
        legend_width = 140
        painter.drawRoundedRect(x - 6, y - 6, legend_width, legend_height, 6, 6)

        for idx, ground_type in enumerate(used_types):
            color_name = color_from_ground_type(ground_type) or "#808080"
            color = QtGui.QColor(color_name)
            color.setAlpha(200)

            painter.setBrush(color)
            painter.setPen(QtGui.QPen(QtGui.QColor("black")))
            painter.drawRect(x, y + idx * line_height, box_size, box_size)

            label = self.LEGEND_LABELS.get(ground_type, f"Type {ground_type}")
            painter.setPen(QtGui.QPen(QtGui.QColor("white")))
            painter.drawText(
                x + box_size + 6,
                y + idx * line_height + box_size - 2,
                label,
            )

    # ------------------------------------------------------------------
    # Public setters
    # ------------------------------------------------------------------
    def set_scale_factor(self, factor: float) -> None:
        self._scale_factor = max(0.1, min(3.0, factor))
        self._autosize_window()
        self.update()

    # ------------------------------------------------------------------
    # Dragging support
    # ------------------------------------------------------------------
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


BaseOverlay.register(ExperimentalTrackSurfaceOverlay)
