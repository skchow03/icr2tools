"""
reader.py

MemoryReader: translates raw memory (via ICR2Memory) to a RaceState (model.RaceState).
All parsing/mapping logic lives here; no UI code in this module.

Updated to compute last_lap_ms from per-car clock fields:
    last_lap_ms = (clock_end_field23 - clock_start_field22) & 0xFFFFFFFF
This handles unsigned wrap correctly and avoids using field 33 (which is personal-best).

Now also reads field 24 (laps_down) to show how many laps behind the leader each car is.
Now also reads field 37 (car_status) to detect retirement reasons.

NEW: also exports the full 0x214 block decoded as 133 signed i32s in CarState.values
so the overlay can show arbitrary indices as custom columns.
"""

import logging
log = logging.getLogger(__name__)

from typing import Dict, List, Optional, Callable
import html

from icr2_core.icr2_memory import ICR2Memory
from icr2timing.core.config import Config
from icr2_core.model import Driver, CarState, RaceState
from icr2_core.memory_io import read_i32 as default_read_i32, read_i32_list as default_read_i32_list
from icr2_core.car_state_decoder import decode_car_states
from icr2_core.track_detector import TrackDetector

class ReadError(RuntimeError):
    """Raised when a required read is missing or invalid."""
    pass


class MemoryReader:
    """
    MemoryReader reads memory using ICR2Memory and returns RaceState snapshots.

    It is constructed with an ICR2Memory instance and a Config instance.
    """

    def __init__(
        self,
        mem: ICR2Memory,
        cfg: Config,
        *,
        track_detector: Optional[TrackDetector] = None,
        read_i32_fn: Callable[[ICR2Memory, int], Optional[int]] = default_read_i32,
        read_i32_list_fn: Callable[[ICR2Memory, int, int], List[int]] = default_read_i32_list,
        car_state_decoder: Callable[[bytes, Config, int], Dict[int, CarState]] = decode_car_states,
    ):

        log.info("Initializing MemoryReader")

        self._mem = mem
        self._cfg = cfg
        self._last_read_error: Optional[str] = None
        self._read_error_count = 0
        self._track_detector = track_detector or TrackDetector(mem, cfg, ReadError)
        self._read_i32_fn = read_i32_fn
        self._read_i32_list_fn = read_i32_list_fn
        self._car_state_decoder = car_state_decoder

    def read_raw_car_count(self) -> int:
        """Read raw car count (including pace car). Raise ReadError on failure."""
        v = self._read_i32_fn(self._mem, self._cfg.cars_addr)
        if v is None:
            raise ReadError(f"no car-count at 0x{self._cfg.cars_addr:X}")
        if v <= 0 or v > self._cfg.max_cars:
            raise ReadError(f"invalid car-count {v} at 0x{self._cfg.cars_addr:X}")
        return v

    def read_total_laps(self) -> int:
        """Read total race laps from memory. Raise ReadError on failure."""
        v = self._read_i32_fn(self._mem, self._cfg.laps_addr)
        if v is None:
            raise ReadError(f"no laps at 0x{self._cfg.laps_addr:X}")
        if v <= 0 or v > self._cfg.max_laps:
            raise ReadError(f"invalid total_laps {v} at 0x{self._cfg.laps_addr:X}")
        return v

    def read_session_timer_ms(self) -> Optional[int]:
        """Return the session timer in milliseconds if available."""
        addr = getattr(self._cfg, "session_timer_addr", 0) or 0
        if addr <= 0:
            return None

        raw = self._read_i32_fn(self._mem, addr)
        if raw is None:
            return None

        return int(raw) & 0xFFFFFFFF

    def _read_names_full(self, raw_count: int) -> Dict[int, str]:
        """
        Read contiguous name slots sized to raw_count and return a map struct_index -> name.
        Name decoding: NUL-terminated ASCII, trimmed and HTML-escaped.

        IMPORTANT: respects names_index_base and names_shift from Config.
        """
        total_bytes = raw_count * self._cfg.entry_bytes_name
        raw = self._mem.read(self._cfg.driver_names_base, 'bytes', count=total_bytes)
        blob = bytes(raw) if isinstance(raw, (bytes, bytearray)) else bytes(raw or b"")
        if len(blob) < total_bytes:
            blob = blob.ljust(total_bytes, b'\x00')

        out: Dict[int, str] = {}
        base = self._cfg.names_index_base
        shift = self._cfg.names_shift
        for struct_idx in range(raw_count):
            slot = struct_idx + base + shift
            start = slot * self._cfg.entry_bytes_name
            end = start + self._cfg.entry_bytes_name
            if start < 0 or end > len(blob):
                out[struct_idx] = ""
                continue
            chunk = blob[start:end]
            name_raw = chunk.split(b'\x00', 1)[0]
            out[struct_idx] = html.escape(name_raw.decode('ascii', errors='ignore').strip())
        return out

    def _read_numbers_full(self, raw_count: int) -> Dict[int, Optional[int]]:
        """Read car numbers table and return a mapping struct_index -> int|None.

        IMPORTANT: respects numbers_index_base and numbers_shift from Config.
        """
        # read a bit extra to be safe if shift is negative
        vals = self._read_i32_list_fn(
            self._mem,
            self._cfg.car_numbers_base,
            raw_count + abs(self._cfg.numbers_shift) + 4
        )
        out: Dict[int, Optional[int]] = {}
        base = self._cfg.numbers_index_base
        shift = self._cfg.numbers_shift
        for struct_idx in range(raw_count):
            slot = struct_idx + base + shift
            out[struct_idx] = int(vals[slot]) if 0 <= slot < len(vals) else None
        return out

    def _read_order_struct_indices(self, raw_count: int, display_count: int) -> List[Optional[int]]:
        """
        Read running order and translate to 0-based struct indices.

        IMPORTANT: respects order_index_base; also drops pace car (struct index 0)
        and returns exactly display_count entries (padded with None).
        """
        vals = self._read_i32_list_fn(self._mem, self._cfg.run_order_base, raw_count)
        out: List[Optional[int]] = []
        for v in vals:
            idx = (v - 1) if self._cfg.order_index_base == 1 else v
            if not (0 <= idx < raw_count):
                continue
            if idx == 0:
                # skip pace car
                continue
            out.append(idx)
            if len(out) == display_count:
                break
        while len(out) < display_count:
            out.append(None)
        return out

    def _read_laps_full(self, raw_count: int, total_laps: int) -> Dict[int, CarState]:
        """
        Read car_state blob sized to raw_count and compute CarState for each struct index.

        last_lap_ms computed from two per-car clock fields (cfg.field_lap_clock_start/ end).
        If either clock is a known sentinel (0xFF000000 / -16777216) or missing -> last_lap_valid=False.
        
        Also reads laps_down from field 24 to show how many laps behind the leader each car is.
        Also reads car_status from field 37 to detect retirement reasons.

        NEW: decodes the entire 0x214 block as signed ints and stores in CarState.values.
        """
        total_bytes = raw_count * self._cfg.car_state_size
        raw = self._mem.read(self._cfg.car_state_base, 'bytes', count=total_bytes)
        blob = bytes(raw) if isinstance(raw, (bytes, bytearray)) else bytes(raw or b"")
        if len(blob) < total_bytes:
            blob = blob.ljust(total_bytes, b'\x00')

        return self._car_state_decoder(blob, self._cfg, total_laps)

    # --- public API ---

    def read_track_length_miles(self) -> float:
        """Read track length from memory and convert to miles."""
        v = self._read_i32_fn(self._mem, self._cfg.track_length_addr)
        if v is None or v <= 0:
            return 0.0
        inches = v / 500.0
        miles = inches / (12 * 5280)
        return miles

    def read_current_track(self) -> str:
        """
        Detect current track folder name.
        - WINDY101: read integer track index at 0x527D58 and map to the
          alphabetical list of track folders (sorted by TNAME).
          Returns the track's subfolder name (e.g. 'CLEVLAND').
        - DOS/REND32A: read string at current_track_addr.
        """
        return self._track_detector.read_current_track()



    def read_race_state(self) -> RaceState:
        """
        Read the full RaceState. Raises ReadError if required reads fail.
        This method is deterministic given memory contents and the config.
        """
        try:
            raw_count = self.read_raw_car_count()
            # display_count excludes pace car
            if raw_count <= 1:
                raise ReadError(f"unexpected raw_count {raw_count}")
            display_count = raw_count - 1

            total_laps = self.read_total_laps()

            # read full maps sized to raw_count
            names_map = self._read_names_full(raw_count)
            numbers_map = self._read_numbers_full(raw_count)
            car_states_map = self._read_laps_full(raw_count, total_laps)

            # build Driver objects for all struct indices
            drivers: Dict[int, Driver] = {}
            for struct_idx in range(raw_count):
                name = names_map.get(struct_idx, "")
                num = numbers_map.get(struct_idx)
                drivers[struct_idx] = Driver(struct_index=struct_idx, name=name, car_number=num)

            order = self._read_order_struct_indices(raw_count, display_count)

            track_length = self.read_track_length_miles()
            track_name = self.read_current_track()
            session_timer_ms = self.read_session_timer_ms()

            if self._last_read_error is not None:
                log.info(f"Memory read recovered after {self._read_error_count} failures")
                self._last_read_error = None
                self._read_error_count = 0

            return RaceState(
                raw_count=raw_count,
                display_count=display_count,
                total_laps=total_laps,
                order=order,
                drivers=drivers,
                car_states={k: v for k, v in car_states_map.items()},
                track_length=track_length,
                track_name=track_name,
                session_timer_ms=session_timer_ms,
            )
        except Exception as e:
            err_str = str(e)

            # log this specific error only the first time it happens
            if err_str != self._last_read_error:
                log.warning(f"Memory read failed: {err_str}")
                self._last_read_error = err_str
                self._read_error_count = 1
            else:
                # silently increment, but no log spam
                self._read_error_count += 1

            raise ReadError(err_str)
