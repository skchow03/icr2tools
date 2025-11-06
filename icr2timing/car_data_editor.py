"""Stand-alone PyQt5 app for inspecting and editing ICR2 car-state blocks.

The tool displays the 133-value runtime struct for the currently selected car
and writes changes straight back to game memory.  It reuses the existing memory
reader + updater stack so reads happen on a worker thread while the UI stays
responsive.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

# When launched as `python icr2timing/car_data_editor.py`, ensure package imports work
if __package__ is None:
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from icr2_core.icr2_memory import ICR2Memory, WindowNotFoundError
from icr2_core.model import RaceState
from icr2_core.reader import MemoryReader
from icr2timing.core.config import Config
from ui.car_value_helpers import (
    CarValueRecorderController,
    FrozenValueStore,
    ValueBarDelegate,
    ValueRangeTracker,
    default_record_output_dir,
    parse_input_value,
)
from icr2timing.updater.updater import RaceUpdater


log = logging.getLogger(__name__)


@dataclass
class CarDisplayInfo:
    struct_index: int
    label: str


class CarDataEditorWidget(QtWidgets.QWidget):
    """Widget that shows all per-car fields and lets the user edit them."""

    def __init__(
        self,
        updater: RaceUpdater,
        mem: Optional[ICR2Memory],
        cfg: Config,
        status_callback: Optional[Callable[[str, int], None]] = None,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._updater = updater
        self._mem = mem
        self._cfg = cfg
        self._status_callback = status_callback

        self._latest_state: Optional[RaceState] = None
        self._car_infos: List[CarDisplayInfo] = []
        self._current_struct_index: Optional[int] = None
        self._updating_table = False
        self._values_per_car = cfg.car_state_size // 4
        self._locked_values = FrozenValueStore()
        self._range_tracker = ValueRangeTracker(self._values_per_car)
        self._record_output_dir = default_record_output_dir()
        self._recorder_ctrl = CarValueRecorderController(
            self._record_output_dir, self._values_per_car
        )

        self._build_ui()
        self._update_enabled_state()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Car selector row
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)

        self._car_combo = QtWidgets.QComboBox()
        self._car_combo.currentIndexChanged.connect(self._on_car_selected)

        self._prev_btn = QtWidgets.QToolButton()
        self._prev_btn.setText("◀")
        self._prev_btn.clicked.connect(self._select_previous_car)

        self._next_btn = QtWidgets.QToolButton()
        self._next_btn.setText("▶")
        self._next_btn.clicked.connect(self._select_next_car)

        row.addWidget(QtWidgets.QLabel("Car:"))
        row.addWidget(self._car_combo, 1)
        row.addWidget(self._prev_btn)
        row.addWidget(self._next_btn)
        layout.addLayout(row)

        instructions = QtWidgets.QLabel(
            "Double-click a value to edit.  Enter decimal or hex (0x...) and press Enter"
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        self._freeze_checkbox = QtWidgets.QCheckBox("Freeze edited values")
        self._freeze_checkbox.setToolTip(
            "When enabled, edited values are written back to memory every update."
        )
        self._freeze_checkbox.toggled.connect(self._on_freeze_toggled)
        layout.addWidget(self._freeze_checkbox)

        record_row = QtWidgets.QHBoxLayout()
        record_row.setSpacing(6)

        record_row.addWidget(QtWidgets.QLabel("Recording:"))

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

        layout.addLayout(record_row)

        self._table = QtWidgets.QTableWidget(self._values_per_car, 2, self)
        self._table.setHorizontalHeaderLabels(["Index", "Value"])
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked)
        self._table.itemChanged.connect(self._on_item_changed)
        self._value_delegate = ValueBarDelegate(self._get_value_range_for_row, self._table)
        self._table.setItemDelegateForColumn(1, self._value_delegate)

        font = QtGui.QFont(self._cfg.font_family, max(8, self._cfg.font_size))
        self._table.setFont(font)
        metrics = QtGui.QFontMetrics(font)
        self._table.verticalHeader().setDefaultSectionSize(metrics.height() + 6)

        for row_idx in range(self._values_per_car):
            index_item = QtWidgets.QTableWidgetItem(f"{row_idx:03d}")
            index_item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled)
            self._table.setItem(row_idx, 0, index_item)
            value_item = QtWidgets.QTableWidgetItem("0")
            value_item.setFlags(
                QtCore.Qt.ItemIsSelectable
                | QtCore.Qt.ItemIsEnabled
                | QtCore.Qt.ItemIsEditable
            )
            self._table.setItem(row_idx, 1, value_item)

        layout.addWidget(self._table, 1)

    # ------------------------------------------------------------------
    def _show_status(self, message: str, timeout_ms: int = 0) -> None:
        if self._status_callback is not None:
            try:
                self._status_callback(message, timeout_ms)
            except TypeError:
                # Some callbacks (like QStatusBar.showMessage) accept default timeout arg only
                self._status_callback(message)  # type: ignore[misc]

    def _update_enabled_state(self) -> None:
        has_mem = self._mem is not None
        widgets = [
            self._car_combo,
            self._prev_btn,
            self._next_btn,
            self._freeze_checkbox,
            self._record_button,
            self._record_every_spin,
            self._table,
        ]
        for widget in widgets:
            widget.setEnabled(has_mem)
        if not has_mem:
            self._record_status_label.setText("Not connected to memory")

    # ------------------------------------------------------------------
    @QtCore.pyqtSlot(int)
    def _on_car_selected(self, combo_index: int) -> None:
        if not (0 <= combo_index < len(self._car_infos)):
            self._current_struct_index = None
            self._clear_values()
            return
        struct_index = self._car_infos[combo_index].struct_index
        if struct_index == self._current_struct_index:
            return
        self._current_struct_index = struct_index
        if self._recorder_ctrl.recorder is not None:
            try:
                self._recorder_ctrl.change_car_index(struct_index)
            except Exception as exc:
                log.exception("Failed to switch recorder car index")
                self._show_status(f"Recorder error: {exc}", 5000)
                self._stop_recording(save_message=False)
            else:
                self._update_record_status()
        self._refresh_table()

    def _select_previous_car(self) -> None:
        idx = self._car_combo.currentIndex()
        if idx > 0:
            self._car_combo.setCurrentIndex(idx - 1)

    def _select_next_car(self) -> None:
        idx = self._car_combo.currentIndex()
        if 0 <= idx < self._car_combo.count() - 1:
            self._car_combo.setCurrentIndex(idx + 1)

    # ------------------------------------------------------------------
    @QtCore.pyqtSlot(object)
    def on_state_updated(self, state: RaceState) -> None:
        self._latest_state = state
        self._show_status(
            f"Track: {state.track_name or 'UNKNOWN'} | Cars: {state.display_count}", 3000
        )
        self._update_car_list(state)
        self._refresh_table()
        self._apply_locked_values()
        if self._recorder_ctrl.recorder is not None:
            try:
                self._recorder_ctrl.record_state(state)
            except Exception as exc:
                log.exception("Failed to record car data")
                self._show_status(f"Recorder error: {exc}", 5000)
                self._stop_recording(save_message=False)

    @QtCore.pyqtSlot(str)
    def on_error(self, message: str) -> None:
        self._show_status(f"Error: {message}", 5000)

    # ------------------------------------------------------------------
    def _update_car_list(self, state: RaceState) -> None:
        new_infos: List[CarDisplayInfo] = []
        for struct_index, driver in state.drivers.items():
            # Skip pace car (struct index 0) by default
            if struct_index == 0:
                continue
            label_bits: List[str] = []
            if driver.car_number is not None:
                label_bits.append(f"#{driver.car_number}")
            if driver.name:
                label_bits.append(driver.name)
            if not label_bits:
                label_bits.append(f"Struct {struct_index}")
            display = " - ".join(label_bits)
            display += f" (idx {struct_index})"
            new_infos.append(CarDisplayInfo(struct_index, display))

        # Stable sort by struct index to avoid reordering jitter
        new_infos.sort(key=lambda info: info.struct_index)

        if self._car_infos == new_infos:
            return

        current_idx = self._current_struct_index
        self._car_infos = new_infos
        valid_structs = {info.struct_index for info in new_infos}
        self._range_tracker.retain_structs(valid_structs)
        self._locked_values.retain_structs(valid_structs)
        self._car_combo.blockSignals(True)
        self._car_combo.clear()
        for info in new_infos:
            self._car_combo.addItem(info.label)
        self._car_combo.blockSignals(False)

        if not new_infos:
            self._current_struct_index = None
            self._clear_values()
            return

        # Try to keep previous selection
        if current_idx is not None:
            for combo_idx, info in enumerate(new_infos):
                if info.struct_index == current_idx:
                    self._car_combo.setCurrentIndex(combo_idx)
                    break
            else:
                self._car_combo.setCurrentIndex(0)
        else:
            self._car_combo.setCurrentIndex(0)

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
        if self._latest_state is None or self._current_struct_index is None:
            return

        car = self._latest_state.car_states.get(self._current_struct_index)
        if car is None:
            self._show_status(
                f"Struct {self._current_struct_index} not present in memory", 3000
            )
            return

        values = car.values
        self._updating_table = True
        try:
            for row_idx in range(self._values_per_car):
                item = self._table.item(row_idx, 1)
                if item is None:
                    continue
                val = values[row_idx] if row_idx < len(values) else 0
                if (
                    self._freeze_checkbox.isChecked()
                    and self._current_struct_index is not None
                ):
                    locked_val = self._locked_values.get(
                        self._current_struct_index, row_idx
                    )
                    if locked_val is not None:
                        val = locked_val
                if self._current_struct_index is not None:
                    self._range_tracker.update(
                        self._current_struct_index, row_idx, val
                    )
                item.setData(QtCore.Qt.UserRole, val)
                item.setText(str(val))
        finally:
            self._updating_table = False
        self._table.viewport().update()

    # ------------------------------------------------------------------
    def _parse_input_value(self, text: str) -> Optional[int]:
        return parse_input_value(text)

    @QtCore.pyqtSlot(QtWidgets.QTableWidgetItem)
    def _on_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        if self._updating_table:
            return
        if item.column() != 1:
            return
        row_idx = item.row()
        if self._current_struct_index is None:
            return

        new_val = self._parse_input_value(item.text())
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
            + self._current_struct_index * self._cfg.car_state_size
            + row_idx * 4
        )

        try:
            self._mem.write(exe_offset, "i32", new_val)
        except Exception as exc:
            log.exception("Failed to write car data value")
            self._show_status(f"Write failed: {exc}", 5000)
            self._refresh_table()
            return

        if self._freeze_checkbox.isChecked():
            self._locked_values.set(self._current_struct_index, row_idx, new_val)

        if self._current_struct_index is not None:
            self._range_tracker.update(self._current_struct_index, row_idx, new_val)
        self._updating_table = True
        try:
            item.setData(QtCore.Qt.UserRole, new_val)
        finally:
            self._updating_table = False
        self._table.viewport().update()

        self._show_status(
            f"Field {row_idx} updated to {new_val} for struct {self._current_struct_index}",
            2000,
        )

    # ------------------------------------------------------------------
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

    def _apply_locked_values(self) -> None:
        if not self._freeze_checkbox.isChecked():
            return
        state = self._latest_state
        if state is None:
            return
        if self._mem is None:
            return

        for struct_index, row_map in self._locked_values.iter_structs():
            if not row_map:
                continue
            if struct_index not in state.car_states:
                continue
            for row_idx, value in row_map.items():
                exe_offset = (
                    self._cfg.car_state_base
                    + struct_index * self._cfg.car_state_size
                    + row_idx * 4
                )
                try:
                    self._mem.write(exe_offset, "i32", value)
                except Exception as exc:
                    log.exception("Failed to maintain frozen car data value")
                    self._show_status(
                        f"Freeze write failed for struct {struct_index}, field {row_idx}: {exc}",
                        5000,
                    )

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self._stop_recording(save_message=False)
        super().closeEvent(event)

    def _toggle_recording(self) -> None:
        if self._recorder_ctrl.recorder is None:
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self) -> None:
        if self._current_struct_index is None:
            self._show_status("Select a car to record", 3000)
            return
        if self._mem is None:
            self._show_status("Memory connection not available", 3000)
            return
        every_n = max(1, int(self._record_every_spin.value()))
        try:
            self._recorder_ctrl.start(self._current_struct_index, every_n=every_n)
        except Exception as exc:
            log.exception("Failed to start car data recording")
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
        every_n = recorder.every_n
        self._record_status_label.setText(
            f"Recording {filename or '(unknown)'} every {every_n} frame(s)"
        )

    def _on_record_every_changed(self, value: int) -> None:
        try:
            self._recorder_ctrl.set_every_n(value)
        except Exception as exc:
            log.exception("Failed to update recorder interval")
            self._show_status(f"Recorder error: {exc}", 5000)
            self._stop_recording(save_message=False)
            return
        if self._recorder_ctrl.recorder is not None:
            self._update_record_status()


    def _get_value_range_for_row(
        self, row_idx: int
    ) -> Tuple[Optional[int], Optional[int]]:
        return self._range_tracker.get(self._current_struct_index, row_idx)

    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        self._stop_recording(save_message=False)


class CarDataEditor(QtWidgets.QMainWindow):
    """Main window wrapper that embeds :class:`CarDataEditorWidget`."""

    def __init__(self, updater: RaceUpdater, mem: ICR2Memory, cfg: Config):
        super().__init__()
        self._updater = updater

        self.setWindowTitle("ICR2 Car Data Editor")
        self.resize(640, 720)

        status_bar = self.statusBar()
        self._widget = CarDataEditorWidget(
            updater,
            mem,
            cfg,
            status_callback=status_bar.showMessage,
            parent=self,
        )
        self.setCentralWidget(self._widget)

        if self._updater is not None:
            self._updater.state_updated.connect(self._widget.on_state_updated)
            self._updater.error.connect(self._widget.on_error)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self._widget.shutdown()
        super().closeEvent(event)


# ----------------------------------------------------------------------
def _create_memory() -> Optional[ICR2Memory]:
    try:
        return ICR2Memory(verbose=False)
    except WindowNotFoundError as e:
        QtWidgets.QMessageBox.critical(
            None,
            "ICR2 Car Data Editor",
            str(e),
            QtWidgets.QMessageBox.Ok,
            QtWidgets.QMessageBox.Ok,
        )
    except Exception as exc:
        QtWidgets.QMessageBox.critical(
            None,
            "ICR2 Car Data Editor",
            f"Unexpected error: {exc}",
            QtWidgets.QMessageBox.Ok,
            QtWidgets.QMessageBox.Ok,
        )
    return None


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    cfg = Config()
    mem: Optional[ICR2Memory] = None
    while mem is None:
        mem = _create_memory()
        if mem is None:
            reply = QtWidgets.QMessageBox.question(
                None,
                "ICR2 Car Data Editor",
                "Unable to attach to ICR2. Retry?",
                QtWidgets.QMessageBox.Retry | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.Retry,
            )
            if reply == QtWidgets.QMessageBox.Cancel:
                return

    reader = MemoryReader(mem, cfg)
    updater = RaceUpdater(reader, poll_ms=max(100, cfg.poll_ms))

    window = CarDataEditor(updater, mem, cfg)
    window.show()

    thread = QtCore.QThread()
    updater.moveToThread(thread)

    def _cleanup() -> None:
        try:
            if updater and thread.isRunning():
                QtCore.QMetaObject.invokeMethod(
                    updater, "stop", QtCore.Qt.BlockingQueuedConnection
                )
        except Exception:
            pass
        try:
            if thread.isRunning():
                thread.quit()
                if not thread.wait(2000):
                    thread.terminate()
                    thread.wait(1000)
        except Exception:
            pass
        try:
            mem.close()
        except Exception:
            pass

    app.aboutToQuit.connect(_cleanup)

    thread.start()
    QtCore.QMetaObject.invokeMethod(updater, "start", QtCore.Qt.QueuedConnection)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
