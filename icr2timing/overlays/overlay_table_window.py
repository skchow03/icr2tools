"""
overlay_table_window.py

Pure UI container: borderless translucent window holding one or more QTableWidgets.
Draggable, minimal padding, small font. No race-specific logic.
"""

from typing import Optional, List
import math
from PyQt5 import QtCore, QtWidgets, QtGui

from core.config import Config

cfg = Config()

class OverlayTableWindow(QtWidgets.QWidget):
    """Borderless translucent window holding one or more QTableWidgets, draggable."""

    def __init__(self, font_family="Arial", font_size=10, n_columns: int = 2):
        super().__init__()
        flags = (
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.Tool
            | QtCore.Qt.WindowStaysOnTopHint
        )
#        flags = QtCore.Qt.FramelessWindowHint | QtCore.Qt.Window
        self.setWindowFlags(flags)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)

        self.n_columns = max(1, n_columns)
        self.tables: List[QtWidgets.QTableWidget] = []

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)  # no gaps between tables

        for _ in range(self.n_columns):
            t = QtWidgets.QTableWidget()
            self._configure_table(t, font_family, font_size)
            self.tables.append(t)
            layout.addWidget(t)

        # Dragging support
        self._drag_pos: Optional[QtCore.QPoint] = None
        for t in self.tables:
            t.viewport().installEventFilter(self)
            t.horizontalHeader().installEventFilter(self)

    def _configure_table(self, t, font_family, font_size):
        f = QtGui.QFont(font_family)
        f.setPointSize(font_size)
        t.setFont(f)
        t.horizontalHeader().setFont(f)

        fm = QtGui.QFontMetrics(f)
        row_h = fm.height() + 2
        t.verticalHeader().setDefaultSectionSize(row_h)
        t.verticalHeader().setMinimumSectionSize(row_h)

        # stylesheet + filler background fix
        t.setStyleSheet(
            f"""
            QTableWidget {{
                background: rgba({cfg.background_rgba});
                color: {cfg.text_color};
                gridline-color: {cfg.grid_color};
            }}
            QHeaderView::section {{
                background: {cfg.header_bg};
                color: {cfg.header_fg};
                padding: 0px 2px;
                margin: 0px;
            }}
            QHeaderView {{
                background: {cfg.header_bg};
            }}
            QTableWidget::item {{
                padding: 0px;
                margin: 0px;
            }}
            """
        )


        header = t.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
        header.setStretchLastSection(False)  # avoid Qt auto-stretching
        t.setShowGrid(False)
        t.verticalHeader().setVisible(False)
        t.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        t.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        t.setWordWrap(False)
        t.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        t.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

    # --- Event filter for dragging ---
    def eventFilter(self, source, event):
        if any(source in (t.viewport(), t.horizontalHeader()) for t in self.tables):
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

    # --- Helpers ---
    def set_headers(self, labels: List[str]):
        for t in self.tables:
            t.setColumnCount(len(labels))
            t.setHorizontalHeaderLabels(labels)
            header = t.horizontalHeader()
            header.setSectionResizeMode(QtWidgets.QHeaderView.Fixed)

    def set_row_count(self, n: int):
        rows_per_table = math.ceil(n / self.n_columns)
        for t in self.tables:
            t.setRowCount(rows_per_table)

    def resize_to_fit(self):
        """Resize outer overlay to exactly wrap contents, no filler headers."""
        total_w, total_h = 0, 0
        for t in self.tables:
            header_h = t.horizontalHeader().height()
            rows_h = sum(t.rowHeight(i) for i in range(t.rowCount()))
            cols_w = sum(t.columnWidth(i) for i in range(t.columnCount()))
            margins = self.layout().contentsMargins()
            extra = t.verticalHeader().width() + (t.frameWidth() * 2)

            # exact content size
            w = cols_w + extra + margins.left() + margins.right()
            h = header_h + rows_h + margins.top() + margins.bottom() + (t.frameWidth() * 2)

            # enforce min size for layout
            t.setMinimumWidth(w)
            t.setMinimumHeight(h)

            total_w += w
            total_h = max(total_h, h)

        spacing = self.layout().spacing() * (len(self.tables) - 1)
        self.resize(total_w + spacing + cfg.fudge_px, total_h)

    def autosize_columns_to_contents(self):
        """Resize each column to fit its contents once, then resize the window."""
        for t in self.tables:
            for c in range(t.columnCount()):
                t.resizeColumnToContents(c)
        self.resize_to_fit()
