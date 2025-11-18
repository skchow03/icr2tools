"""
telemetry_laps.py

Logs a line each time a car crosses the finish line.
Uses the in-game lap_end_clock (ms) as the timestamp.
Each session creates a timestamped CSV file (e.g. telemetry_laps_2025-10-08_00-53-42.csv).
"""
import logging
log = logging.getLogger(__name__)

import csv
import os
import datetime
from typing import Optional, TextIO
from icr2_core.model import RaceState


class TelemetryLapLogger:
    def __init__(self, base_name: str = "telemetry_laps"):
        # Create timestamped filename
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.file_path = f"{base_name}_{timestamp}.csv"

        self._file: Optional[TextIO] = None
        self._writer: Optional[csv.writer] = None
        self._last_end_clock = {}  # struct_idx -> previous lap_end_clock

        # Ensure folder exists if base_name includes directories
        folder = os.path.dirname(self.file_path)
        if folder and not os.path.exists(folder):
            os.makedirs(folder)

        # Create CSV header and keep handle for incremental writes
        self._file = open(self.file_path, "w", newline="")
        self._writer = csv.writer(self._file)
        self._writer.writerow(["timestamp_s", "car_number", "lap", "last_lap_ms"])
        self._file.flush()

        log.info(f"[LapLogger] Logging to {self.file_path}")

    def get_filename(self) -> str:
        """Return the current CSV filename."""
        return os.path.basename(self.file_path)

    def on_state_updated(self, state: RaceState):
        if not self._writer:
            return

        try:
            for idx, car in state.car_states.items():
                if not car or not car.last_lap_valid:
                    continue

                prev_clock = self._last_end_clock.get(idx)
                if prev_clock is not None and car.lap_end_clock == prev_clock:
                    continue  # same lap

                self._last_end_clock[idx] = car.lap_end_clock

                # Skip invalid or zero times
                if car.last_lap_ms <= 0:
                    continue

                driver = state.drivers.get(idx)
                car_number = driver.car_number if driver else None
                #name = driver.name if driver else ""
                lap_time = car.last_lap_ms /1000.0  # convert to seconds
                lap_num = car.laps_completed

                # Convert lap_end_clock (ms) to seconds for timestamp
                timestamp = round((car.lap_end_clock or 0) / 1000.0, 3)

                self._writer.writerow([timestamp, car_number, lap_num, lap_time])
                if self._file:
                    self._file.flush()

                #print(f"[LapLogger] Lap {lap_num} - #{car_number} {name} ({lap_time} ms, t={timestamp}s)")

        except Exception as e:
            log.error(f"[LapLogger] Error logging lap: {e}")

    def close(self) -> None:
        """Flush and close the CSV file, resetting state for future sessions."""

        try:
            if self._file:
                self._file.flush()
                self._file.close()
        finally:
            self._file = None
            self._writer = None
            self._last_end_clock = {}

    def __enter__(self):  # pragma: no cover - convenience only
        return self

    def __exit__(self, exc_type, exc, tb):  # pragma: no cover - convenience only
        self.close()
