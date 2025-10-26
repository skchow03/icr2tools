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

from typing import Dict, List, Optional
import html

from icr2_core.icr2_memory import ICR2Memory
from icr2timing.core.config import Config
from icr2_core.model import Driver, CarState, RaceState

import os
import re

class ReadError(RuntimeError):
    """Raised when a required read is missing or invalid."""
    pass


class MemoryReader:
    """
    MemoryReader reads memory using ICR2Memory and returns RaceState snapshots.

    It is constructed with an ICR2Memory instance and a Config instance.
    """

    _cached_tracks = None
    _cached_index = None
    

    def __init__(self, mem: ICR2Memory, cfg: Config):

        log.info("Initializing MemoryReader")

        self._mem = mem
        self._cfg = cfg
        self._last_read_error: Optional[str] = None
        self._read_error_count = 0

    # --- low-level reading helpers ---

    def _read_i32(self, addr: int) -> Optional[int]:
        """Read a single i32 from memory. Returns None on short/absent reads."""
        raw = self._mem.read(addr, 'i32', count=1)
        if raw is None:
            return None
        if isinstance(raw, int):
            return raw
        if isinstance(raw, (bytes, bytearray)):
            if len(raw) < 4:
                return None
            return int.from_bytes(raw[:4], 'little', signed=False)
        try:
            # sequence (list/tuple)
            return int(raw[0]) if raw else None
        except Exception:
            return None

    def _read_i32_list(self, addr: int, count: int) -> List[int]:
        """Read up to count i32s and return as list (may be shorter)."""
        raw = self._mem.read(addr, 'i32', count=count)
        if raw is None:
            return []
        if isinstance(raw, int):
            return [raw]
        if isinstance(raw, (bytes, bytearray)):
            n = len(raw) // 4
            return [int.from_bytes(raw[i*4:(i+1)*4], 'little', signed=False) for i in range(n)]
        try:
            return [int(x) for x in raw]
        except Exception:
            return []

    # --- higher-level readers used for RaceState ---

    def read_raw_car_count(self) -> int:
        """Read raw car count (including pace car). Raise ReadError on failure."""
        v = self._read_i32(self._cfg.cars_addr)
        if v is None:
            raise ReadError(f"no car-count at 0x{self._cfg.cars_addr:X}")
        if v <= 0 or v > self._cfg.max_cars:
            raise ReadError(f"invalid car-count {v} at 0x{self._cfg.cars_addr:X}")
        return v

    def read_total_laps(self) -> int:
        """Read total race laps from memory. Raise ReadError on failure."""
        v = self._read_i32(self._cfg.laps_addr)
        if v is None:
            raise ReadError(f"no laps at 0x{self._cfg.laps_addr:X}")
        if v <= 0 or v > self._cfg.max_laps:
            raise ReadError(f"invalid total_laps {v} at 0x{self._cfg.laps_addr:X}")
        return v

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
        vals = self._read_i32_list(
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
        vals = self._read_i32_list(self._cfg.run_order_base, raw_count)
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

        # known sentinel: 0xFF000000 (unsigned) often appears as -16777216 if interpreted signed
        SENTINEL_UNSIGNED = 0xFF000000
        SENTINEL_SIGNED = -16777216

        out: Dict[int, CarState] = {}
        for struct_idx in range(raw_count):
            base = struct_idx * self._cfg.car_state_size

            # laps_left (field 32)
            start_ll = base + self._cfg.field_laps_left
            raw4 = blob[start_ll:start_ll+4]
            if len(raw4) < 4:
                laps_left = 0
            else:
                laps_left = int.from_bytes(raw4, 'little', signed=False)

            # current_lap (field 38)
            start_ll = base + self._cfg.current_lap
            raw4 = blob[start_ll:start_ll+4]
            if len(raw4) < 4:
                current_lap = 0
            else:
                current_lap = int.from_bytes(raw4, 'little', signed=False) - 1
            if current_lap < 0:
                current_lap = 0

            # lap clock start (field 22 or cfg.field_lap_clock_start)
            start_clock = base + self._cfg.field_lap_clock_start
            raw4_start = blob[start_clock:start_clock+4]
            if len(raw4_start) < 4:
                clock_start = None
            else:
                clock_start_val = int.from_bytes(raw4_start, 'little', signed=False)
                signed_start = int.from_bytes(raw4_start, 'little', signed=True)
                if clock_start_val == SENTINEL_UNSIGNED or signed_start == SENTINEL_SIGNED:
                    clock_start = None
                else:
                    clock_start = clock_start_val

            # lap clock end (field 23 or cfg.field_lap_clock_end)
            end_clock = base + self._cfg.field_lap_clock_end
            raw4_end = blob[end_clock:end_clock+4]
            if len(raw4_end) < 4:
                clock_end = None
            else:
                clock_end_val = int.from_bytes(raw4_end, 'little', signed=False)
                signed_end = int.from_bytes(raw4_end, 'little', signed=True)
                if clock_end_val == SENTINEL_UNSIGNED or signed_end == SENTINEL_SIGNED:
                    clock_end = None
                else:
                    clock_end = clock_end_val

            # laps down (field 24)
            laps_down_offset = base + self._cfg.field_laps_down
            raw4_laps_down = blob[laps_down_offset:laps_down_offset+4]
            if len(raw4_laps_down) < 4:
                laps_down = 0
            else:
                laps_down = int.from_bytes(raw4_laps_down, 'little', signed=False)
                # Clamp to reasonable range - field 24 should be 0 for lead lap, positive for laps down
                if laps_down > 100:  # sanity check
                    laps_down = 0

            # possibly LP line (field 52)
            car_offset = base + self._cfg.current_lp
            raw4_current_lp = blob[car_offset:car_offset+4]
            current_lp = int.from_bytes(raw4_current_lp, 'little', signed=False)

            # fuel laps remaining (field 35)
            fuel_offset = base + self._cfg.fuel_laps_remaining
            raw4_fuel = blob[fuel_offset:fuel_offset+4]
            fuel_laps_remaining = int.from_bytes(raw4_fuel, 'little', signed=False)

            # car status (field 37)
            car_status_offset = base + self._cfg.car_status
            raw4_car_status = blob[car_status_offset:car_status_offset+4]
            if len(raw4_car_status) < 4:
                car_status = 0
            else:
                car_status = int.from_bytes(raw4_car_status, 'little', signed=False)
                # Clamp to reasonable range - should be 0-16 based on retirement reasons
                if car_status > 16:
                    car_status = 0

            # DLAT (field 11)
            dlat_offset = base + self._cfg.dlat
            raw4_dlat = blob[dlat_offset:dlat_offset+4]
            dlat = int.from_bytes(raw4_dlat, 'little', signed=True) if len(raw4_dlat) == 4 else 0

            # DLONG (field 31)
            dlong_offset = base + self._cfg.dlong
            raw4_dlong = blob[dlong_offset:dlong_offset+4]
            dlong = int.from_bytes(raw4_dlong, 'little', signed=True) if len(raw4_dlong) == 4 else 0

            # compute last_lap_ms if both clocks are valid; otherwise mark invalid
            if clock_start is None or clock_end is None:
                last_lap_ms = 0
                last_lap_valid = False
            else:
                last_lap_ms = (clock_end - clock_start) & 0xFFFFFFFF
                last_lap_valid = True

            # Old way to compute laps run
            # completed = total_laps - laps_left
            # if completed < 0:
            #     completed = 0
            # if completed > total_laps:
            #     completed = total_laps

            # NEW: full 0x214 block decoded as signed i32s for research/custom fields
            values: List[int] = [
                int.from_bytes(blob[base + i*4: base + (i+1)*4], 'little', signed=True)
                for i in range(self._cfg.car_state_size // 4)
            ]

            out[struct_idx] = CarState(
                struct_index=struct_idx,
                laps_left=laps_left,
                laps_completed=current_lap,
                last_lap_ms=last_lap_ms,
                last_lap_valid=last_lap_valid,
                laps_down=laps_down,
                lap_end_clock=clock_end,
                lap_start_clock=clock_start,
                car_status=car_status,
                current_lp=current_lp,
                fuel_laps_remaining=fuel_laps_remaining,
                dlat=dlat,
                dlong=dlong,
                values=values,  # <-- keep the raw block too
            )
        return out

    # --- public API ---

    def read_track_length_miles(self) -> float:
        """Read track length from memory and convert to miles."""
        v = self._read_i32(self._cfg.track_length_addr)
        if v is None or v <= 0:
            return 0.0
        inches = v / 500.0
        miles = inches / (12 * 5280)
        return miles

    def read_current_track(self) -> str:
        """
        Detect current track folder name.
        - WINDY: read integer track index at 0x527D58 and map to the
          alphabetical list of track folders (sorted by TNAME).
          Returns the track's subfolder name (e.g. 'CLEVLAND').
        - DOS/REND32A: read string at current_track_addr.
        """
        version = getattr(self._cfg, "version", "").upper()

        # --- WINDY mode ---
        if version == "WINDY":
            idx = self._mem.read(0x527D58, "i32")

            # Use cached list if available and index unchanged
            if (
                hasattr(self, "_cached_tracks")
                and hasattr(self, "_cached_index")
                and self._cached_tracks is not None
                and idx == self._cached_index
            ):
                try:
                    return self._cached_tracks[idx][0]  # folder name
                except Exception:
                    pass  # rebuild if cache invalid

            exe_path = self._cfg.game_exe
            if not exe_path:
                raise ReadError("game_exe not set in settings.ini")

            tracks_root = os.path.join(os.path.dirname(exe_path), "TRACKS")
            if not os.path.isdir(tracks_root):
                raise ReadError(f"TRACKS folder not found: {tracks_root}")

            # Build alphabetical list from TNAME lines
            tname_pattern = re.compile(r"^\s*TNAME\s+(.+)$", re.IGNORECASE | re.MULTILINE)
            track_entries = []

            for sub in os.listdir(tracks_root):
                sub_path = os.path.join(tracks_root, sub)
                if not os.path.isdir(sub_path):
                    continue
                txt_path = os.path.join(sub_path, f"{sub}.TXT")
                if not os.path.isfile(txt_path):
                    continue
                try:
                    with open(txt_path, "r", errors="ignore") as f:
                        txt = f.read()
                    m = tname_pattern.search(txt)
                    if not m:
                        continue
                    display_name = m.group(1).strip()
                    track_entries.append((sub, display_name))
                except Exception:
                    continue

            if not track_entries:
                raise ReadError("no valid tracks found under TRACKS folder")

            # Sort alphabetically by display name, but we’ll return folder name
            track_entries.sort(key=lambda x: x[1].lower())

            if not (0 <= idx < len(track_entries)):
                raise ReadError(f"track index {idx} out of range")

            # Cache list and index
            self._cached_tracks = track_entries
            self._cached_index = idx

            return track_entries[idx][0]  # folder name

        # --- DOS / REND32A fallback ---
        raw = self._mem.read(self._cfg.current_track_addr, 'bytes', count=256)
        if raw is None:
            raise ReadError(f"no track name at 0x{self._cfg.current_track_addr:X}")

        blob = bytes(raw) if isinstance(raw, (bytes, bytearray)) else bytes(raw or b"")
        name_raw = blob.split(b'\x00', 1)[0]
        return name_raw.decode('ascii', errors='ignore').strip()



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
