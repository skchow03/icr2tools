"""
individual_car_overlay.py

Overlay for inspecting and editing individual car telemetry values in real time.
Now hardened: all memory writes are gated by version and layout checks.
"""

import struct
from PyQt5 import QtWidgets, QtCore, QtGui
from icr2timing.core.icr2_memory import ICR2Memory, WindowNotFoundError


class IndividualCarOverlay(QtWidgets.QWidget):
    """Displays and allows editing of telemetry fields for a single car."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Individual Car Telemetry")
        self.setGeometry(100, 100, 420, 600)
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.Tool
            | QtCore.Qt.WindowStaysOnTopHint
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)

        self._mem = None
        self._cfg = None
        self._freeze = False
        self._frozen_values = {}
        self.car_index = 0
        self._last_state = None
        self._version = None

        # --- Layout setup ---
        layout = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Field", "Value", "Offset"])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        self._freeze_checkbox = QtWidgets.QCheckBox("Freeze edited values")
        layout.addWidget(self._freeze_checkbox)

        self._status = QtWidgets.QLabel("")
        layout.addWidget(self._status)

        self._freeze_checkbox.stateChanged.connect(self._on_freeze_toggled)
        self.table.itemChanged.connect(self._on_item_changed)

        self.hide()

    # ----------------------------------------
    # Public API
    # ----------------------------------------
    def set_memory(self, mem: ICR2Memory, cfg):
        self._mem = mem
        self._cfg = cfg
        self._version = getattr(mem, "detected_version", None)
        self._status.setText(f"Attached to {self._version or 'Unknown'}")

    def set_car_index(self, idx: int):
        self.car_index = idx

    def on_state_updated(self, state):
        if not state or self._mem is None:
            return
        self._last_state = state
        if not self._freeze:
            self._populate_from_state(state)

    def on_error(self, msg: str):
        self._status.setText(f"Error: {msg}")
        # Disable freeze mode on any memory error
        if self._freeze:
            self._freeze_checkbox.setChecked(False)

    # ----------------------------------------
    # Internal safety helpers
    # ----------------------------------------
    def _writes_allowed(self) -> bool:
        """Return True only if it's safe to write."""
        if not self._mem:
            return False
        # Ensure layout validated and version matches config
        if not getattr(self._mem, "layout_ok", True):
            return False
        if self._version and self._cfg and self._version.upper() != self._cfg.version.upper():
            return False
        return True

    def _show_status(self, text: str, ms: int = 2500):
        self._status.setText(text)
        QtCore.QTimer.singleShot(ms, lambda: self._status.setText(""))

    # ----------------------------------------
    # Freeze handling
    # ----------------------------------------
    def _on_freeze_toggled(self, state):
        self._freeze = state == QtCore.Qt.Checked
        if not self._freeze:
            self._frozen_values.clear()
            self._show_status("Freeze disabled", 1500)
        else:
            if not self._writes_allowed():
                self._freeze_checkbox.setChecked(False)
                self._show_status("Cannot enable freeze: invalid layout", 3000)
                return
            self._record_frozen_values()
            self._show_status("Freeze enabled", 1500)

    def _record_frozen_values(self):
        """Cache the current field values to reapply when frozen."""
        self._frozen_values.clear()
        for row in range(self.table.rowCount()):
            label = self.table.item(row, 0).text()
            value = self.table.item(row, 1).text()
            offset = int(self.table.item(row, 2).text(), 16)
            self._frozen_values[label] = (offset, value)

    def _apply_locked_values(self):
        """Write frozen values back to memory each frame."""
        if not self._freeze or not self._writes_allowed():
            return
        try:
            for label, (offset, value_str) in self._frozen_values.items():
                try:
                    val = int(value_str)
                    addr = self._cfg.car_state_base + self.car_index * self._cfg.car_state_size + offset
                    self._mem.write(addr, "i32", val)
                except Exception:
                    continue
        except Exception as e:
            self._show_status(f"Write error: {e}", 3000)
            self._freeze_checkbox.setChecked(False)

    # ----------------------------------------
    # Manual editing
    # ----------------------------------------
    def _on_item_changed(self, item):
        if not self._writes_allowed():
            return
        row = item.row()
        col = item.column()
        if col != 1:
            return
        try:
            val = int(item.text())
        except ValueError:
            self._show_status("Invalid integer", 1500)
            return
        offset = int(self.table.item(row, 2).text(), 16)
        addr = self._cfg.car_state_base + self.car_index * self._cfg.car_state_size + offset
        try:
            self._mem.write(addr, "i32", val)
            self._show_status(f"Wrote {val} to +0x{offset:X}", 1000)
        except Exception as e:
            self._show_status(f"Write failed: {e}", 3000)
            self._freeze_checkbox.setChecked(False)

    # ----------------------------------------
    # Populate and display
    # ----------------------------------------
    def _populate_from_state(self, state):
        """Fill the table with readable values from the selected car."""
        driver = state.drivers.get(self.car_index)
        if not driver:
            return

        self.table.blockSignals(True)
        self.table.setRowCount(0)

        def add_row(name, value, offset):
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(name))
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(str(value)))
            self.table.setItem(r, 2, QtWidgets.QTableWidgetItem(f"{offset:04X}"))

        add_row("Speed", int(driver.speed_mph), 0x000)
        add_row("Throttle", int(driver.throttle * 100), 0x010)
        add_row("Brake", int(driver.brake * 100), 0x014)
        add_row("Gear", int(driver.gear), 0x018)
        add_row("RPM", int(driver.rpm), 0x01C)
        add_row("Fuel", int(driver.fuel), 0x020)

        self.table.blockSignals(False)

    # ----------------------------------------
    # Paint / frame updates
    # ----------------------------------------
    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 180))
        painter.setPen(QtGui.QPen(QtGui.QColor("white")))
        painter.drawText(10, 20, f"Car #{self.car_index}")
        if self._freeze:
            self._apply_locked_values()
        painter.end()
