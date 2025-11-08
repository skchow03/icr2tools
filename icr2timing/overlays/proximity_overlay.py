# proximity_overlay.py
#
# Upgraded and fixed radar overlay for ICR2 Timing.
# Restores proper scaling/orientation from original version while adding:
# - configurable radar size, range, and car dimensions
# - distinct colors for player / ahead / behind / alongside
# - optional relative speed display
# - symbol styles: rectangle / circle / arrow
# - translucent background + reference grid
#
# All parameters read from [radar] in settings.ini via Config().

from PyQt5 import QtCore, QtGui, QtWidgets
from icr2timing.overlays.base_overlay import BaseOverlay
from icr2_core.model import RaceState
from icr2timing.core.config import Config

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def parse_rgba(s: str) -> QtGui.QColor:
    """Parse 'r,g,b,a' string into QColor."""
    if not s:
        return QtGui.QColor(255, 255, 255, 255)
    if "," in s:
        parts = [int(x) for x in s.split(",")]
        while len(parts) < 4:
            parts.append(255)
        return QtGui.QColor(*parts)
    return QtGui.QColor(s)


def clamp(v, lo, hi):
    return max(lo, min(v, hi))


# ------------------------------------------------------------
# Main Overlay
# ------------------------------------------------------------

class ProximityOverlay(QtWidgets.QWidget):
    """Configurable radar overlay showing relative car positions."""

    def __init__(self):
        super().__init__()
        self.cfg = Config()

        flags = (
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.Tool
            | QtCore.Qt.WindowStaysOnTopHint
        )
        # flags = QtCore.Qt.FramelessWindowHint | QtCore.Qt.Window
        self.setWindowFlags(flags)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.resize(self.cfg.radar_width, self.cfg.radar_height)

        self._last_state: RaceState | None = None
        self._drag_pos: QtCore.QPoint | None = None
        self.installEventFilter(self)

        self._update_ranges_from_cfg()

    # --------------------------------------------------------
    # Config reload
    # --------------------------------------------------------
    def _update_ranges_from_cfg(self):
        c = self.cfg
        car_len_units = c.radar_car_length_in * 500
        car_wid_units = c.radar_car_width_in * 500

        self.range_forward = c.radar_range_forward * car_len_units
        self.range_rear = c.radar_range_rear * car_len_units
        self.range_side = c.radar_range_side * car_wid_units

        self.car_len_units = car_len_units
        self.car_wid_units = car_wid_units

        self.color_player = parse_rgba(c.radar_player_color)
        self.color_ahead = parse_rgba(c.radar_ai_ahead_color)
        self.color_behind = parse_rgba(c.radar_ai_behind_color)
        self.color_along = parse_rgba(c.radar_ai_alongside_color)
        self.background = parse_rgba(c.radar_background)

        self.symbol = getattr(c, "radar_symbol", "rectangle").lower()
        self.show_speeds = getattr(c, "radar_show_speeds", False)

    def apply_config(self, cfg: Config):
        """Replace the backing Config and refresh derived values."""
        self.cfg = cfg
        self._update_ranges_from_cfg()
        self.update()

    # --------------------------------------------------------
    # Runtime mutators (for ControlPanel live updates)
    # --------------------------------------------------------
    def set_size(self, w: int, h: int):
        self.resize(clamp(w, 100, 1200), clamp(h, 100, 1200))
        self.update()

    def set_range(self, forward=None, rear=None, side=None):
        if forward is not None:
            self.cfg.radar_range_forward = forward
        if rear is not None:
            self.cfg.radar_range_rear = rear
        if side is not None:
            self.cfg.radar_range_side = side
        self._update_ranges_from_cfg()
        self.update()

    def set_symbol(self, style: str):
        self.symbol = style.lower()
        self.update()

    def set_show_speeds(self, enabled: bool):
        self.show_speeds = bool(enabled)
        self.update()

    def set_colors(self, player=None, ahead=None, behind=None, alongside=None):
        if player:
            self.color_player = parse_rgba(player)
        if ahead:
            self.color_ahead = parse_rgba(ahead)
        if behind:
            self.color_behind = parse_rgba(behind)
        if alongside:
            self.color_along = parse_rgba(alongside)
        self.update()

    # --------------------------------------------------------
    # BaseOverlay API
    # --------------------------------------------------------
    def widget(self):
        return self

    def on_state_updated(self, state: RaceState, update_bests: bool = True):
        self._last_state = state
        self.update()

    def on_error(self, msg: str):
        self._last_state = None
        self.update()

    # --------------------------------------------------------
    # Painting
    # --------------------------------------------------------
    def paintEvent(self, event):
        if not self.cfg:
            return

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), self.background)

        if not self._last_state:
            return

        c = self.cfg
        player = self._last_state.car_states.get(c.player_index)
        if not player:
            return

        cx, cy = self.width() / 2.0, self.height() / 2.0

        # scale calculation (same as original)
        sx = (self.width() / 2.0) / self.range_side
        sy = (self.height() / 2.0) / max(self.range_forward, self.range_rear)
        scale = min(sx, sy)

        # coordinate transform (match original)
        def to_screen(dx_units, dy_units):
            rx = cx - dx_units * scale           # DLAT reversed
            ry = cy - dy_units * scale           # DLONG forward = up
            return rx, ry

        # grid + crosshair
        painter.setPen(QtGui.QPen(QtGui.QColor(100, 100, 100, 80), 1))
        painter.drawRect(0, 0, self.width() - 1, self.height() - 1)
        painter.drawLine(QtCore.QPointF(0.0, cy), QtCore.QPointF(float(self.width()), cy))
        painter.drawLine(QtCore.QPointF(cx, 0.0), QtCore.QPointF(cx, float(self.height())))

        # car symbol size
        car_w_px = self.car_wid_units * scale
        car_l_px = self.car_len_units * scale

        # player
        painter.setBrush(QtGui.QBrush(self.color_player))
        painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0)))
        self._draw_symbol(painter, cx, cy, car_w_px, car_l_px, self.symbol)

        track_len_units = (self._last_state.track_length or 0) * 5280 * 12 * 500

        # AI cars
        for idx, car in self._last_state.car_states.items():
            if not car or idx == c.player_index:
                continue

            dx = car.dlat - player.dlat
            dy = car.dlong - player.dlong

            if track_len_units > 0:
                dy = (dy + track_len_units / 2) % track_len_units - track_len_units / 2

            # cull outside window
            if dy > self.range_forward or dy < -self.range_rear or abs(dx) > self.range_side:
                continue

            rx, ry = to_screen(dx, dy)

            # classify relative position
            if dy > self.car_len_units:
                color = self.color_ahead
            elif dy < -self.car_len_units:
                color = self.color_behind
            else:
                color = self.color_along

            painter.setBrush(QtGui.QBrush(color))
            painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0)))
            self._draw_symbol(painter, rx, ry, car_w_px, car_l_px, self.symbol)

            # relative speed text
            if self.show_speeds:
                try:
                    my_speed = abs(player.values[18])
                    ai_speed = abs(car.values[18])
                    delta = ai_speed - my_speed
                    painter.setPen(QtGui.QPen(QtGui.QColor("white")))
                    painter.drawText(rx + 5, ry, f"{delta:+.0f}")
                except Exception:
                    pass

    # --------------------------------------------------------
    # Draw shape helper
    # --------------------------------------------------------
    def _draw_symbol(self, painter, cx, cy, w, l, style: str):
        style = style.lower()
        if style == "circle":
            painter.drawEllipse(QtCore.QPointF(cx, cy), w / 2, l / 2)
        elif style == "arrow":
            points = [
                QtCore.QPointF(cx, cy - l / 2),
                QtCore.QPointF(cx - w / 2, cy + l / 2),
                QtCore.QPointF(cx + w / 2, cy + l / 2),
            ]
            painter.drawPolygon(QtGui.QPolygonF(points))
        else:
            painter.drawRect(QtCore.QRectF(cx - w / 2, cy - l / 2, w, l))

    # --------------------------------------------------------
    # Dragging support
    # --------------------------------------------------------
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


# register virtual subclass
BaseOverlay.register(ProximityOverlay)
