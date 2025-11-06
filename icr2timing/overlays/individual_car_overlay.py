"""Interactive overlay for inspecting and editing a single car's telemetry."""
from __future__ import annotations

import logging
import os
from typing import Callable, Optional, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

from overlays.base_overlay import BaseOverlay
from icr2_core.model import RaceState
from core.config import Config
from ui.car_value_helpers import (
    CarValueRecorderController,
    FrozenValueStore,
    ValueBarDelegate,
    ValueRangeTracker,
    default_record_output_dir,
    parse_input_value,
)

log = logging.getLogger(__name__)


class DraggableTable(QtWidgets.QTableWidget):
    """QTableWidget that optionally drags the parent overlay when left-clicked."""

    def __init__(self, parent_overlay: QtWidgets.QWidget, enable_drag: bool) -> None:
        super().__init__(parent_overlay)
        self._parent_overlay = parent_overlay
        self._enable_drag = enable_drag
        self._drag_pos: Optional[QtCore.QPoint] = None

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # type: ignore[override]
        if (
            self._enable_drag
            and event.button() == QtCore.Qt.LeftButton
            and self.itemAt(event.pos()) is None
        ):
            self._drag_pos = event.globalPos() - self._parent_overlay.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # type: ignore[override]
        if (
            self._enable_drag
            and self._drag_pos is not None
            and event.buttons() & QtCore.Qt.LeftButton
        ):
            self._parent_overlay.move(event.globalPos() - self._drag_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # type: ignore[override]
        self._drag_pos = None
        super().mouseReleaseEvent(event)


class IndividualCarOverlay(QtWidgets.QWidget):
    """Draggable overlay showing and editing all raw car-state values for one car."""

    def __init__(
        self,
        mem=None,
        cfg: Optional[Config] = None,
        status_callback: Optional[Callable[[str, int], None]] = None,
        car_index: int = 1,
    ) -> None:
        super().__init__()
        self._cfg = cfg or Config()
        self._mem = mem
        self._status_callback = status_callback
        self._car_index = int(car_index)

        self._values_per_car = self._cfg.car_state_size // 4
        self._latest_state: Optional[RaceState] = None
        self._updating_table = False
        self._range_tracker = ValueRangeTracker(self._values_per_car)
        self._locked_values = FrozenValueStore()
        self._recorder_ctrl = CarValueRecorderController(
            default_record_output_dir(), self._values_per_car
        )

        flags = QtCore.Qt.Window | QtCore.Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)

        self._build_ui()
        self._update_enabled_state()
        self._update_title()

    # ------------------------------------------------------------------
    @property
    def car_index(self) -> int:
        return self._car_index

    @car_index.setter
    def car_index(self, value: int) -> None:
        self.set_car_index(value)

    # ------------------------------------------------------------------
    def set_status_callback(
        self, callback: Optional[Callable[[str, int], None]]
    ) -> None:
        self._status_callback = callback

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(0)

        frame = QtWidgets.QFrame(self)
        frame.setObjectName("overlayContainer")
        frame_layout = QtWidgets.QVBoxLayout(frame)
        frame_layout.setContentsMargins(10, 10, 10, 10)
        frame_layout.setSpacing(6)
        main_layout.addWidget(frame)

        title_font = QtGui.QFont(self._cfg.font_family, max(10, self._cfg.font_size + 1))
        self._title_label = QtWidgets.QLabel("Car ???")
        self._title_label.setAlignment(QtCore.Qt.AlignCenter)
        self._title_label.setFont(title_font)
        frame_layout.addWidget(self._title_label)

        instructions = QtWidgets.QLabel(
            "Double-click a value to edit. Use decimal or 0x-prefixed hex values."
        )
        instructions.setWordWrap(True)
        frame_layout.addWidget(instructions)

        self._freeze_checkbox = QtWidgets.QCheckBox("Freeze edited values")
        self._freeze_checkbox.setToolTip(
            "When enabled, edited values are re-applied to memory on each update."
        )
        self._freeze_checkbox.toggled.connect(self._on_freeze_toggled)
        frame_layout.addWidget(self._freeze_checkbox)

        record_row = QtWidgets.QHBoxLayout()
        record_row.setSpacing(6)
        frame_layout.addLayout(record_row)

        self._record_button = QtWidgets.QPushButton("Start")
        self._record_button.clicked.connect(self._toggle_recording)
        record_row.addWidget(self._record_button)

        record_row.addWidget(QtWidgets.QLabel("Every"))
        self._record_every_spin = QtWidgets.QSpinBox()
        self._record_every_spin.setRange(1, 9999)
        self._record_every_spin.setValue(1)
        self._record_every_spin.setToolTip("Record one row every N updates")
        self._record_every_spin.valueChanged.connect(self._on_record_every_changed)
        record_row.addWidget(self._record_every_spin)

        record_row.addWidget(QtWidgets.QLabel("frame(s)"))

        self._record_status_label = QtWidgets.QLabel("Not recording")
        self._record_status_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        record_row.addWidget(self._record_status_label, 1)

        self._table = DraggableTable(self, enable_drag=False)
        self._configure_table()
        frame_layout.addWidget(self._table, 1)

        background_rgb = self._background_rgb()
        frame.setStyleSheet(
            f"""
            QFrame#overlayContainer {{
                background-color: rgb({background_rgb});
                color: {self._cfg.text_color};
                border-radius: 6px;
            }}
            QLabel, QCheckBox {{
                color: {self._cfg.text_color};
            }}
            QPushButton {{
                color: {self._cfg.text_color};
            }}
            QTableWidget {{
                background-color: rgb({background_rgb});
                color: {self._cfg.text_color};
                gridline-color: {self._cfg.grid_color};
            }}
        """
        )

    def _configure_table(self) -> None:
        self._table.setColumnCount(2)
        self._table.setRowCount(self._values_per_car)
        self._table.setHorizontalHeaderLabels(["Index", "Value"])
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)

        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked)

        font = QtGui.QFont(self._cfg.font_family, max(8, self._cfg.font_size))
        self._table.setFont(font)
        metrics = QtGui.QFontMetrics(font)
        self._table.verticalHeader().setDefaultSectionSize(metrics.height() + 6)

        self._value_delegate = ValueBarDelegate(self._value_range_for_row, self._table)
        self._table.setItemDelegateForColumn(1, self._value_delegate)

        for row_idx in range(self._values_per_car):
            index_item = QtWidgets.QTableWidgetItem(f"{row_idx:03d}")
            index_item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled)
            value_item = QtWidgets.QTableWidgetItem("0")
            value_item.setFlags(
                QtCore.Qt.ItemIsSelectable
                | QtCore.Qt.ItemIsEnabled
                | QtCore.Qt.ItemIsEditable
            )
            value_item.setData(QtCore.Qt.UserRole, 0)
            self._table.setItem(row_idx, 0, index_item)
            self._table.setItem(row_idx, 1, value_item)

        self._table.itemChanged.connect(self._on_item_changed)

    def _background_rgb(self) -> str:
        try:
            components = [int(part.strip()) for part in self._cfg.background_rgba.split(",")]
        except ValueError:
            log.warning(
                "Invalid background_rgba value '%s'; falling back to opaque black.",
                self._cfg.background_rgba,
            )
            components = [0, 0, 0]

        if len(components) < 3:
            log.warning(
                "background_rgba value '%s' did not contain RGB components; using black.",
                self._cfg.background_rgba,
            )
            components = [0, 0, 0]

        rgb = [max(0, min(255, value)) for value in components[:3]]
        return ", ".join(str(value) for value in rgb)

    # ------------------------------------------------------------------
    def widget(self):
        return self

    def on_state_updated(self, state: RaceState, update_bests: bool = True):  # noqa: D401
        self._latest_state = state
        self._range_tracker.retain_structs(state.car_states.keys())
        self._locked_values.retain_structs(state.car_states.keys())
        self._update_title()
        self._refresh_table()
        self._apply_locked_values()
        if self._recorder_ctrl.recorder is not None:
            try:
                self._recorder_ctrl.record_state(state)
            except Exception as exc:  # pragma: no cover - defensive
                log.exception("Failed to record car data from overlay")
                self._show_status(f"Recorder error: {exc}", 5000)
                self._stop_recording(save_message=False)

    def on_error(self, msg: str):
        self._show_status(f"Error: {msg}", 5000)

    # ------------------------------------------------------------------
    def set_car_index(self, idx: int) -> None:
        idx = int(idx)
        if idx == self._car_index:
            return
        self._car_index = idx
        if self._recorder_ctrl.recorder is not None:
            try:
                self._recorder_ctrl.change_car_index(idx)
            except Exception as exc:  # pragma: no cover - defensive
                log.exception("Failed to switch recorder car index from overlay")
                self._show_status(f"Recorder error: {exc}", 5000)
                self._stop_recording(save_message=False)
            else:
                self._update_record_status()
        self._update_title()
        self._refresh_table()

    # ------------------------------------------------------------------
    def _update_title(self) -> None:
        if self._latest_state is None:
            self._title_label.setText(f"Car idx {self._car_index}")
            return

        driver = self._latest_state.drivers.get(self._car_index)
        bits = []
        if driver is not None:
            car_number = getattr(driver, "car_number", None)
            if car_number is not None:
                bits.append(f"#{car_number}")
            name = getattr(driver, "name", None)
            if name:
                bits.append(str(name))
        if not bits:
            bits.append(f"Struct {self._car_index}")
        self._title_label.setText(" - ".join(bits))

    def _clear_values(self) -> None:
        self._updating_table = True
        try:
            for row_idx in range(self._values_per_car):
                item = self._table.item(row_idx, 1)
                if item is not None:
                    item.setData(QtCore.Qt.UserRole, 0)
                    item.setText("0")
        finally:
            self._updating_table = False
        self._table.viewport().update()

    def _refresh_table(self) -> None:
        if self._latest_state is None:
            return

        car_state = self._latest_state.car_states.get(self._car_index)
        if car_state is None or not hasattr(car_state, "values"):
            self._clear_values()
            return

        values = car_state.values
        self._updating_table = True
        try:
            for row_idx in range(self._values_per_car):
                item = self._table.item(row_idx, 1)
                if item is None:
                    continue
                val = values[row_idx] if row_idx < len(values) else 0
                if self._freeze_checkbox.isChecked():
                    locked_val = self._locked_values.get(self._car_index, row_idx)
                    if locked_val is not None:
                        val = locked_val
                self._range_tracker.update(self._car_index, row_idx, val)
                item.setData(QtCore.Qt.UserRole, val)
                item.setText(str(val))
        finally:
            self._updating_table = False
        self._table.viewport().update()

    def _apply_locked_values(self) -> None:
        if not self._freeze_checkbox.isChecked():
            return
        if self._mem is None or self._latest_state is None:
            return

        for struct_index, row_map in self._locked_values.iter_structs():
            if not row_map or struct_index not in self._latest_state.car_states:
                continue
            for row_idx, value in row_map.items():
                exe_offset = (
                    self._cfg.car_state_base
                    + struct_index * self._cfg.car_state_size
                    + row_idx * 4
                )
                try:
                    self._mem.write(exe_offset, "i32", value)
                except Exception as exc:  # pragma: no cover - defensive
                    log.exception("Failed to maintain frozen overlay value")
                    self._show_status(
                        f"Freeze write failed for struct {struct_index}, field {row_idx}: {exc}",
                        5000,
                    )

    # ------------------------------------------------------------------
    def _value_range_for_row(self, row_idx: int) -> Tuple[Optional[int], Optional[int]]:
        return self._range_tracker.get(self._car_index, row_idx)

    @QtCore.pyqtSlot(QtWidgets.QTableWidgetItem)
    def _on_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        if self._updating_table:
            return
        if item.column() != 1:
            return

        row_idx = item.row()
        new_val = parse_input_value(item.text())
        if new_val is None:
            self._show_status("Invalid number", 3000)
            self._refresh_table()
            return

        if self._mem is None:
            self._show_status("Memory connection not available", 3000)
            self._refresh_table()
            return

        exe_offset = (
            self._cfg.car_state_base
            + self._car_index * self._cfg.car_state_size
            + row_idx * 4
        )

        try:
            self._mem.write(exe_offset, "i32", new_val)
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("Failed to write car data value from overlay")
            self._show_status(f"Write failed: {exc}", 5000)
            self._refresh_table()
            return

        if self._freeze_checkbox.isChecked():
            self._locked_values.set(self._car_index, row_idx, new_val)

        self._range_tracker.update(self._car_index, row_idx, new_val)
        self._updating_table = True
        try:
            item.setData(QtCore.Qt.UserRole, new_val)
            item.setText(str(new_val))
        finally:
            self._updating_table = False
        self._table.viewport().update()

        self._show_status(
            f"Field {row_idx} updated to {new_val} for struct {self._car_index}", 2000
        )

    def _on_freeze_toggled(self, enabled: bool) -> None:
        if not enabled:
            self._locked_values.clear()
            self._show_status("Value freezing disabled", 2000)
            self._refresh_table()
        else:
            self._show_status(
                "Value freezing enabled. Edited values will be reapplied each update.",
                4000,
            )

    def _toggle_recording(self) -> None:
        if self._recorder_ctrl.recorder is None:
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self) -> None:
        if self._latest_state is None:
            self._show_status("Telemetry not available yet", 3000)
            return
        every_n = max(1, int(self._record_every_spin.value()))
        try:
            self._recorder_ctrl.start(self._car_index, every_n=every_n)
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("Failed to start overlay recorder")
            self._show_status(f"Unable to start recording: {exc}", 5000)
            return

        self._record_button.setText("Stop")
        self._update_record_status()
        filename = self._recorder_ctrl.filename
        if filename:
            self._show_status(f"Recording car data to {filename}", 5000)

    def _stop_recording(self, save_message: bool = True) -> None:
        filename = self._recorder_ctrl.stop()
        self._record_button.setText("Start")
        self._record_status_label.setText("Not recording")
        if save_message and filename:
            self._show_status(f"Recording saved to {filename}", 5000)

    def _update_record_status(self) -> None:
        recorder = self._recorder_ctrl.recorder
        if recorder is None:
            self._record_status_label.setText("Not recording")
            return
        filename = os.path.basename(self._recorder_ctrl.filename or "")
        self._record_status_label.setText(
            f"Recording {filename or '(unknown)'} every {recorder.every_n} frame(s)"
        )

    def _on_record_every_changed(self, value: int) -> None:
        try:
            self._recorder_ctrl.set_every_n(value)
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("Failed to update overlay recorder interval")
            self._show_status(f"Recorder error: {exc}", 5000)
            self._stop_recording(save_message=False)
            return
        if self._recorder_ctrl.recorder is not None:
            self._update_record_status()

    # ------------------------------------------------------------------
    def _update_enabled_state(self) -> None:
        editable = self._mem is not None
        triggers = (
            QtWidgets.QAbstractItemView.DoubleClicked
            if editable
            else QtWidgets.QAbstractItemView.NoEditTriggers
        )
        self._table.setEditTriggers(triggers)
        self._freeze_checkbox.setEnabled(editable)
        if not editable:
            self._freeze_checkbox.setChecked(False)

    def _show_status(self, message: str, timeout_ms: int) -> None:
        if self._status_callback is not None:
            self._status_callback(message, timeout_ms)


BaseOverlay.register(IndividualCarOverlay)
