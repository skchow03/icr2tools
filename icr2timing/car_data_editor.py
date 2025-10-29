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
from typing import Callable, Dict, List, Optional, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

# When launched as `python icr2timing/car_data_editor.py`, ensure package imports work
if __package__ is None:
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from icr2_core.icr2_memory import ICR2Memory, WindowNotFoundError
from icr2_core.model import RaceState
from icr2_core.reader import MemoryReader
from icr2timing.core.car_data_recorder import CarDataRecorder
from icr2timing.core.config import Config
from icr2timing.updater.updater import RaceUpdater


log = logging.getLogger(__name__)


@dataclass
class CarDisplayInfo:
    struct_index: int
    label: str


@dataclass
class ValueRange:
    """Tracks the observed minimum and maximum for a given value index."""

    minimum: Optional[int] = None
    maximum: Optional[int] = None

    def update(self, value: int) -> None:
        if self.minimum is None or value < self.minimum:
            self.minimum = value
        if self.maximum is None or value > self.maximum:
            self.maximum = value


class ValueBarDelegate(QtWidgets.QStyledItemDelegate):
    """Item delegate that renders a bi-directional bar for numeric values."""

    def __init__(
        self,
        range_provider: Callable[[int], Tuple[Optional[int], Optional[int]]],
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._range_provider = range_provider

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> None:
        opt = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        style = opt.widget.style() if opt.widget is not None else QtWidgets.QApplication.style()
        original_text = opt.text
        opt.text = ""
        style.drawControl(QtWidgets.QStyle.CE_ItemViewItem, opt, painter, opt.widget)

        value = index.data(QtCore.Qt.UserRole)
        if value is None:
            try:
                value = int(original_text)
            except (TypeError, ValueError):
                value = None

        rect = opt.rect.adjusted(4, 4, -4, -4)
        if value is not None and rect.width() > 0 and rect.height() > 0:
            min_val, max_val = self._range_provider(index.row())
            min_val = min_val if min_val is not None else 0
            max_val = max_val if max_val is not None else 0

            negative_span = abs(min(0, min_val))
            positive_span = max(0, max_val)

            center_x = rect.center().x()
            left_width_available = center_x - rect.left()
            right_width_available = rect.right() - center_x

            painter.save()
            painter.setRenderHint(QtGui.QPainter.Antialiasing, False)

            if value >= 0 and positive_span > 0 and right_width_available > 0:
                ratio = min(1.0, value / positive_span) if positive_span else 0.0
                width = int(round(ratio * right_width_available))
                if width > 0:
                    bar_rect = QtCore.QRect(center_x, rect.top(), width, rect.height())
                    bar_color = QtGui.QColor(76, 175, 80)
                    if opt.state & QtWidgets.QStyle.State_Selected:
                        bar_color = bar_color.lighter(125)
                    painter.fillRect(bar_rect, bar_color)
            elif value < 0 and negative_span > 0 and left_width_available > 0:
                ratio = min(1.0, abs(value) / negative_span) if negative_span else 0.0
                width = int(round(ratio * left_width_available))
                if width > 0:
                    bar_rect = QtCore.QRect(center_x - width, rect.top(), width, rect.height())
                    bar_color = QtGui.QColor(244, 67, 54)
                    if opt.state & QtWidgets.QStyle.State_Selected:
                        bar_color = bar_color.lighter(125)
                    painter.fillRect(bar_rect, bar_color)

            zero_pen = QtGui.QPen(opt.palette.mid().color())
            if opt.state & QtWidgets.QStyle.State_Selected:
                zero_pen.setColor(opt.palette.highlightedText().color())
            painter.setPen(zero_pen)
            painter.drawLine(center_x, rect.top(), center_x, rect.bottom())

            painter.restore()

        text_rect = opt.rect.adjusted(6, 0, -6, 0)
        painter.save()
        text_color = (
            opt.palette.highlightedText().color()
            if opt.state & QtWidgets.QStyle.State_Selected
            else opt.palette.text().color()
        )
        painter.setPen(text_color)
        painter.drawText(text_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight, original_text)
        painter.restore()


class CarDataEditor(QtWidgets.QMainWindow):
    """Main window that shows all per-car fields and lets the user edit them."""

    def __init__(self, updater: RaceUpdater, mem: ICR2Memory, cfg: Config):
        super().__init__()
        self._updater = updater
        self._mem = mem
        self._cfg = cfg

        self._latest_state: Optional[RaceState] = None
        self._car_infos: List[CarDisplayInfo] = []
        self._current_struct_index: Optional[int] = None
        self._updating_table = False
        self._values_per_car = cfg.car_state_size // 4
        self._locked_values: Dict[int, Dict[int, int]] = {}
        self._value_ranges: Dict[int, List[ValueRange]] = {}
        self._recorder: Optional[CarDataRecorder] = None
        self._record_output_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "car_data_recordings"
        )

        self.setWindowTitle("ICR2 Car Data Editor")
        self.resize(640, 720)

        self._build_ui()

        updater.state_updated.connect(self.on_state_updated)
        updater.error.connect(self.on_error)

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(central)
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

        self._status = QtWidgets.QStatusBar()
        self.setStatusBar(self._status)

        central.setLayout(layout)
        self.setCentralWidget(central)

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
        if self._recorder is not None:
            try:
                self._recorder.change_car_index(struct_index)
            except Exception as exc:
                log.exception("Failed to switch recorder car index")
                self._status.showMessage(f"Recorder error: {exc}", 5000)
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
        self._status.showMessage(
            f"Track: {state.track_name or 'UNKNOWN'} | Cars: {state.display_count}", 3000
        )
        self._update_car_list(state)
        self._refresh_table()
        self._apply_locked_values()
        if self._recorder is not None:
            try:
                self._recorder.record_state(state)
            except Exception as exc:
                log.exception("Failed to record car data")
                self._status.showMessage(f"Recorder error: {exc}", 5000)
                self._stop_recording(save_message=False)

    @QtCore.pyqtSlot(str)
    def on_error(self, message: str) -> None:
        self._status.showMessage(f"Error: {message}", 5000)

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
        self._value_ranges = {
            struct_index: ranges
            for struct_index, ranges in self._value_ranges.items()
            if struct_index in valid_structs
        }
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
            self._status.showMessage(
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
                    locked = self._locked_values.get(self._current_struct_index)
                    if locked is not None and row_idx in locked:
                        val = locked[row_idx]
                if self._current_struct_index is not None:
                    self._update_value_range(self._current_struct_index, row_idx, val)
                item.setData(QtCore.Qt.UserRole, val)
                item.setText(str(val))
        finally:
            self._updating_table = False
        self._table.viewport().update()

    # ------------------------------------------------------------------
    def _parse_input_value(self, text: str) -> Optional[int]:
        text = text.strip()
        if not text:
            return None
        try:
            # Allow 0x.. hex or plain integers
            return int(text, 0)
        except ValueError:
            return None

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
            self._status.showMessage("Invalid number", 3000)
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
            self._status.showMessage(f"Write failed: {exc}", 5000)
            self._refresh_table()
            return

        if self._freeze_checkbox.isChecked():
            locked_for_struct = self._locked_values.setdefault(self._current_struct_index, {})
            locked_for_struct[row_idx] = new_val

        if self._current_struct_index is not None:
            self._update_value_range(self._current_struct_index, row_idx, new_val)
        self._updating_table = True
        try:
            item.setData(QtCore.Qt.UserRole, new_val)
        finally:
            self._updating_table = False
        self._table.viewport().update()

        self._status.showMessage(
            f"Field {row_idx} updated to {new_val} for struct {self._current_struct_index}",
            2000,
        )

    # ------------------------------------------------------------------
    def _on_freeze_toggled(self, enabled: bool) -> None:
        if not enabled:
            self._locked_values.clear()
            self._status.showMessage("Value freezing disabled", 2000)
            self._refresh_table()
        else:
            self._status.showMessage(
                "Value freezing enabled. Edited values will be reapplied each update.",
                4000,
            )

    def _apply_locked_values(self) -> None:
        if not self._freeze_checkbox.isChecked():
            return
        state = self._latest_state
        if state is None:
            return

        for struct_index, row_map in list(self._locked_values.items()):
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
                    self._status.showMessage(
                        f"Freeze write failed for struct {struct_index}, field {row_idx}: {exc}",
                        5000,
                    )

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self._stop_recording(save_message=False)
        super().closeEvent(event)

    def _toggle_recording(self) -> None:
        if self._recorder is None:
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self) -> None:
        if self._current_struct_index is None:
            self._status.showMessage("Select a car to record", 3000)
            return
        every_n = max(1, int(self._record_every_spin.value()))
        try:
            self._recorder = CarDataRecorder(
                output_dir=self._record_output_dir,
                car_index=self._current_struct_index,
                values_per_car=self._values_per_car,
                every_n=every_n,
            )
        except Exception as exc:
            self._recorder = None
            log.exception("Failed to start car data recording")
            self._status.showMessage(f"Unable to start recording: {exc}", 5000)
            return

        self._record_button.setText("Stop")
        self._update_record_status()
        filename = self._recorder.filename
        if filename:
            self._status.showMessage(f"Recording car data to {filename}", 5000)

    def _stop_recording(self, save_message: bool = True) -> None:
        if self._recorder is None:
            return
        filename = self._recorder.filename
        try:
            self._recorder.close()
        finally:
            self._recorder = None
        self._record_button.setText("Start")
        self._record_status_label.setText("Not recording")
        if save_message and filename:
            self._status.showMessage(f"Recording saved to {filename}", 5000)

    def _update_record_status(self) -> None:
        if self._recorder is None:
            self._record_status_label.setText("Not recording")
            return
        filename = os.path.basename(self._recorder.filename or "")
        every_n = self._recorder.every_n
        self._record_status_label.setText(
            f"Recording {filename or '(unknown)'} every {every_n} frame(s)"
        )

    def _on_record_every_changed(self, value: int) -> None:
        if self._recorder is not None:
            try:
                self._recorder.set_every_n(value)
            except Exception as exc:
                log.exception("Failed to update recorder interval")
                self._status.showMessage(f"Recorder error: {exc}", 5000)
                self._stop_recording(save_message=False)
                return
            self._update_record_status()


    def _get_ranges_for_struct(self, struct_index: int) -> List[ValueRange]:
        ranges = self._value_ranges.get(struct_index)
        if ranges is None or len(ranges) != self._values_per_car:
            ranges = [ValueRange() for _ in range(self._values_per_car)]
            self._value_ranges[struct_index] = ranges
        return ranges

    def _get_value_range_for_row(
        self, row_idx: int
    ) -> Tuple[Optional[int], Optional[int]]:
        if self._current_struct_index is None:
            return (None, None)
        ranges = self._value_ranges.get(self._current_struct_index)
        if ranges is None or not (0 <= row_idx < len(ranges)):
            return (None, None)
        info = ranges[row_idx]
        return (info.minimum, info.maximum)

    def _update_value_range(self, struct_index: int, row_idx: int, value: int) -> None:
        ranges = self._get_ranges_for_struct(struct_index)
        if 0 <= row_idx < len(ranges):
            ranges[row_idx].update(value)


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
