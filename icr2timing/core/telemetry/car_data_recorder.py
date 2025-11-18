"""Utility for recording per-frame car telemetry data to CSV."""
from __future__ import annotations

import csv
import json
import os
from datetime import datetime
from typing import Iterable, Optional, Sequence

from icr2_core.model import RaceState

from icr2timing.core.car_field_definitions import (
    CarFieldDefinition,
    ensure_field_definitions,
)


class CarDataRecorder:
    """Records raw car telemetry values to a timestamped CSV file."""

    def __init__(
        self,
        output_dir: str,
        car_index: int,
        values_per_car: int = 133,
        every_n: int = 1,
        field_definitions: Optional[Sequence[CarFieldDefinition]] = None,
        flush_every: Optional[int] = None,
    ) -> None:
        self.output_dir = os.path.abspath(output_dir)
        self.values_per_car = values_per_car
        self._every_n = max(1, int(every_n))
        self._frames_seen = 0
        self._frames_written = 0
        self._writer: Optional[csv.writer] = None
        self._file = None
        self.filename: Optional[str] = None
        self._flush_every = self._normalize_flush_every(flush_every)
        self._rows_since_flush = 0
        if field_definitions is None:
            field_definitions = ensure_field_definitions(values_per_car)
        self._field_definitions: Sequence[CarFieldDefinition] = self._normalize_definitions(
            field_definitions
        )
        self.metadata_filename: Optional[str] = None
        os.makedirs(self.output_dir, exist_ok=True)
        self.change_car_index(car_index)

    @property
    def every_n(self) -> int:
        return self._every_n

    def set_every_n(self, value: int) -> None:
        self._every_n = max(1, int(value))

    def change_car_index(self, car_index: int) -> None:
        """Close the current file (if any) and start a new one for the car."""
        self._close_file()
        self.car_index = int(car_index)
        self._frames_seen = 0
        self._frames_written = 0
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"car_{self.car_index:03d}_{timestamp}.csv"
        self.filename = os.path.join(self.output_dir, filename)
        self._file = open(self.filename, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._rows_since_flush = 0
        header = ["frame", "timestamp_ms", "car_index", "car_number"]
        header.extend(self._header_labels())
        self._writer.writerow(header)
        self._after_write()
        self._write_metadata_file()

    def record_state(self, state: RaceState) -> None:
        """Record the current state for the configured car if interval matches."""
        if self._writer is None:
            return

        self._frames_seen += 1
        if self._frames_seen % self._every_n != 0:
            return

        car_state = state.car_states.get(self.car_index)
        if not car_state:
            return

        values = list(getattr(car_state, "values", []))
        if len(values) < self.values_per_car:
            values.extend([""] * (self.values_per_car - len(values)))
        else:
            values = values[: self.values_per_car]

        self._frames_written += 1

        session_timer_ms = getattr(state, "session_timer_ms", None)
        if session_timer_ms is not None:
            timestamp_value = str(int(session_timer_ms) & 0xFFFFFFFF)
        else:
            timestamp_value = datetime.now().isoformat(timespec="milliseconds")

        row = [
            self._frames_written,
            timestamp_value,
            self.car_index,
            getattr(car_state, "car_number", ""),
        ]
        row.extend(values)
        self._writer.writerow(row)
        self._after_write()

    def close(self) -> None:
        self._close_file()

    def flush(self) -> None:
        if self._file is None:
            return
        self._file.flush()
        self._rows_since_flush = 0

    def _close_file(self) -> None:
        if self._writer is not None:
            self._writer = None
        if self._file is not None:
            try:
                self.flush()
                self._file.close()
            finally:
                self._file = None

    def __enter__(self) -> "CarDataRecorder":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    def _normalize_definitions(
        self, definitions: Sequence[CarFieldDefinition]
    ) -> Sequence[CarFieldDefinition]:
        by_index = {definition.index: definition for definition in definitions}
        fallback = ensure_field_definitions(self.values_per_car)
        ordered = []
        for idx in range(self.values_per_car):
            ordered.append(by_index.get(idx) or fallback[idx])
        return tuple(ordered)

    def _header_labels(self) -> Iterable[str]:
        for definition in self._field_definitions:
            name = definition.name.strip() or f"value_{definition.index:03d}"
            safe_name = name.replace(" ", "_")
            yield f"{definition.index:03d}_{safe_name}"

    def _write_metadata_file(self) -> None:
        if not self.filename:
            self.metadata_filename = None
            return

        metadata = {
            "car_index": self.car_index,
            "values_per_car": self.values_per_car,
            "fields": [
                {
                    "index": definition.index,
                    "name": definition.name,
                    "description": definition.description,
                }
                for definition in self._field_definitions
            ],
        }

        metadata_path = f"{self.filename}.meta.json"
        with open(metadata_path, "w", encoding="utf-8") as meta_file:
            json.dump(metadata, meta_file, indent=2)
        self.metadata_filename = metadata_path

    def _normalize_flush_every(self, value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            return None
        return normalized if normalized > 0 else None

    def _after_write(self) -> None:
        if self._flush_every is None:
            return
        self._rows_since_flush += 1
        if self._rows_since_flush >= self._flush_every:
            self.flush()
