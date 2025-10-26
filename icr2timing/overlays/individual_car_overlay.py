# overlays/individual_car_overlay.py
from PyQt5 import QtWidgets, QtCore, QtGui
from overlays.base_overlay import BaseOverlay
from icr2_core.model import RaceState
from core.config import Config
import math

# ---------------------------------------------
# Subclassed QTableWidget that drags parent window
# ---------------------------------------------
class DraggableTable(QtWidgets.QTableWidget):
    def __init__(self, parent_overlay):
        super().__init__(parent_overlay)
        self._parent_overlay = parent_overlay
        self._drag_pos = None

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_pos = event.globalPos() - self._parent_overlay.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & QtCore.Qt.LeftButton and self._drag_pos is not None:
            self._parent_overlay.move(event.globalPos() - self._drag_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

# ---------------------------------------------
# Main overlay class
# ---------------------------------------------
class IndividualCarOverlay(QtWidgets.QWidget):
    """Draggable overlay showing all 133 raw car-state values for one car."""

    def __init__(self, car_index: int = 1, columns: int = 4):
        super().__init__()
        self.cfg = Config()
        self.car_index = car_index
        self.columns = max(1, columns)
        self.values_per_car = 133

        flags = (
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.Tool
            | QtCore.Qt.WindowStaysOnTopHint
        )
        self.setWindowFlags(flags)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.resize(500, 500)

        # Use our draggable subclass
        self.table = DraggableTable(self)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)

        self._configure_table()
        self._last_state: RaceState | None = None

    # ---------------------------------------------
    def _configure_table(self):
        f = QtGui.QFont(self.cfg.font_family, self.cfg.font_size)
        self.table.setFont(f)
        fm = QtGui.QFontMetrics(f)
        row_h = fm.height() + 2
        self.table.verticalHeader().setDefaultSectionSize(row_h)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(True)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.table.horizontalHeader().setVisible(False)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background: rgba({self.cfg.background_rgba});
                color: {self.cfg.text_color};
                gridline-color: {self.cfg.grid_color};
            }}
        """)

        n_rows = math.ceil(self.values_per_car / self.columns)
        self.table.setRowCount(n_rows)
        self.table.setColumnCount(self.columns)

        # 🔧 Fixed column widths (no resizing)
        for c in range(self.table.columnCount()):
            self.table.setColumnWidth(c, 180)

    # ---------------------------------------------
    # BaseOverlay API
    # ---------------------------------------------
    def widget(self):
        return self

    def on_state_updated(self, state: RaceState, update_bests: bool = True):
        self._last_state = state
        car = state.car_states.get(self.car_index)
        if not car or not hasattr(car, "values"):
            return
        vals = car.values
        n_rows = self.table.rowCount()
        self.table.clearContents()
        for i, v in enumerate(vals[: self.values_per_car]):
            row = i % n_rows
            col = i // n_rows
            item = QtWidgets.QTableWidgetItem(f"{i:03d}: {v}")
            self.table.setItem(row, col, item)

        # (no resizeColumnsToContents here)

    def on_error(self, msg: str):
        self.table.clear()
        self.table.setRowCount(1)
        self.table.setColumnCount(1)
        self.table.setItem(0, 0, QtWidgets.QTableWidgetItem(f"Error: {msg}"))

    def set_car_index(self, idx: int):
        """Change which car index this overlay tracks."""
        self.car_index = idx
        # Immediately refresh the table if we already have a state
        if self._last_state:
            self.on_state_updated(self._last_state)


BaseOverlay.register(IndividualCarOverlay)
