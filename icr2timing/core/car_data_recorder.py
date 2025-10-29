"""Utility for recording per-frame car telemetry data to CSV."""
from __future__ import annotations

import csv
import os
from datetime import datetime
from typing import Optional

from icr2_core.model import RaceState


class CarDataRecorder:
    """Records raw car telemetry values to a timestamped CSV file."""

    def __init__(
        self,
        output_dir: str,
        car_index: int,
        values_per_car: int = 133,
        every_n: int = 1,
    ) -> None:
        self.output_dir = os.path.abspath(output_dir)
        self.values_per_car = values_per_car
        self._every_n = max(1, int(every_n))
        self._frames_seen = 0
        self._frames_written = 0
        self._writer: Optional[csv.writer] = None
        self._file = None
        self.filename: Optional[str] = None
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
        header = ["frame", "timestamp", "car_index", "car_number"]
        header.extend(f"value_{i:03d}" for i in range(self.values_per_car))
        self._writer.writerow(header)
        self._file.flush()

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

        row = [
            self._frames_written,
            datetime.now().isoformat(timespec="milliseconds"),
            self.car_index,
            getattr(car_state, "car_number", ""),
        ]
        row.extend(values)
        self._writer.writerow(row)
        self._file.flush()

    def close(self) -> None:
        self._close_file()

    def _close_file(self) -> None:
        if self._writer is not None:
            self._writer = None
        if self._file is not None:
            try:
                self._file.close()
            finally:
                self._file = None

    def __enter__(self) -> "CarDataRecorder":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
