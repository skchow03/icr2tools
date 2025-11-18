"""Shared helpers for editing and recording raw car telemetry values."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional, Sequence, Tuple, TYPE_CHECKING

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2timing.core.telemetry.car_data_recorder import CarDataRecorder
from icr2timing.core.car_field_definitions import (
    CarFieldDefinition,
    ensure_field_definitions,
)

if TYPE_CHECKING:  # pragma: no cover - only for type checking
    from icr2_core.model import RaceState
else:
    RaceState = Any  # type: ignore


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
            data_index = index.data(QtCore.Qt.UserRole + 1)
            if isinstance(data_index, int):
                min_val, max_val = self._range_provider(data_index)
            else:
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


def parse_input_value(text: str) -> Optional[int]:
    """Parse decimal or 0x-prefixed hex strings into integers."""

    value = text.strip()
    if not value:
        return None
    try:
        return int(value, 0)
    except ValueError:
        return None


class ValueRangeTracker:
    """Maintains observed value ranges for each struct index."""

    def __init__(self, values_per_car: int) -> None:
        self._values_per_car = values_per_car
        self._ranges: Dict[int, Tuple[ValueRange, ...]] = {}

    def update(self, struct_index: int, row_idx: int, value: int) -> None:
        ranges = self._ensure_struct(struct_index)
        if 0 <= row_idx < len(ranges):
            ranges[row_idx].update(value)

    def get(self, struct_index: Optional[int], row_idx: int) -> Tuple[Optional[int], Optional[int]]:
        if struct_index is None:
            return (None, None)
        ranges = self._ranges.get(struct_index)
        if ranges is None or not (0 <= row_idx < len(ranges)):
            return (None, None)
        info = ranges[row_idx]
        return (info.minimum, info.maximum)

    def retain_structs(self, valid_structs: Iterable[int]) -> None:
        valid = set(valid_structs)
        self._ranges = {idx: ranges for idx, ranges in self._ranges.items() if idx in valid}

    def clear(self) -> None:
        self._ranges.clear()

    def _ensure_struct(self, struct_index: int) -> Tuple[ValueRange, ...]:
        ranges = self._ranges.get(struct_index)
        if ranges is None or len(ranges) != self._values_per_car:
            ranges = tuple(ValueRange() for _ in range(self._values_per_car))
            self._ranges[struct_index] = ranges
        return ranges


class FrozenValueStore:
    """Keeps track of frozen (locked) values per struct index."""

    def __init__(self) -> None:
        self._locked: Dict[int, Dict[int, int]] = {}

    def set(self, struct_index: int, row_idx: int, value: int) -> None:
        self._locked.setdefault(struct_index, {})[row_idx] = value

    def get(self, struct_index: int, row_idx: int) -> Optional[int]:
        struct_map = self._locked.get(struct_index)
        if struct_map is None:
            return None
        return struct_map.get(row_idx)

    def clear(self) -> None:
        self._locked.clear()

    def retain_structs(self, valid_structs: Iterable[int]) -> None:
        valid = set(valid_structs)
        self._locked = {idx: rows for idx, rows in self._locked.items() if idx in valid}

    def iter_structs(self) -> Iterable[Tuple[int, Dict[int, int]]]:
        return list(self._locked.items())


class CarValueRecorderController:
    """Thin wrapper around :class:`CarDataRecorder` for reuse between widgets."""

    def __init__(
        self,
        output_dir: str,
        values_per_car: int,
        field_definitions: Optional[Sequence[CarFieldDefinition]] = None,
    ) -> None:
        self._output_dir = os.path.abspath(output_dir)
        self._values_per_car = values_per_car
        if field_definitions is None:
            field_definitions = ensure_field_definitions(values_per_car)
        self._field_definitions: Tuple[CarFieldDefinition, ...] = tuple(field_definitions)
        self._recorder: Optional[CarDataRecorder] = None
        self._last_every_n = 1

    @property
    def recorder(self) -> Optional[CarDataRecorder]:
        return self._recorder

    @property
    def filename(self) -> Optional[str]:
        return None if self._recorder is None else self._recorder.filename

    @property
    def metadata_filename(self) -> Optional[str]:
        if self._recorder is None:
            return None
        return getattr(self._recorder, "metadata_filename", None)

    @property
    def every_n(self) -> int:
        if self._recorder is not None:
            return self._recorder.every_n
        return self._last_every_n

    def start(self, car_index: int, every_n: int = 1) -> CarDataRecorder:
        self.stop()
        self._last_every_n = max(1, int(every_n))
        self._recorder = CarDataRecorder(
            output_dir=self._output_dir,
            car_index=car_index,
            values_per_car=self._values_per_car,
            every_n=self._last_every_n,
            field_definitions=self._field_definitions,
        )
        return self._recorder

    def stop(self) -> Optional[str]:
        if self._recorder is None:
            return None
        filename = self._recorder.filename
        try:
            self._recorder.close()
        finally:
            self._recorder = None
        return filename

    def change_car_index(self, car_index: int) -> None:
        if self._recorder is not None:
            self._recorder.change_car_index(car_index)

    def set_every_n(self, value: int) -> None:
        self._last_every_n = max(1, int(value))
        if self._recorder is not None:
            self._recorder.set_every_n(value)

    def record_state(self, state: "RaceState") -> None:  # type: ignore[override]
        if self._recorder is not None:
            self._recorder.record_state(state)


def default_record_output_dir() -> str:
    """Return the shared car data recordings directory."""

    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(base_dir, "..", "car_data_recordings"))
