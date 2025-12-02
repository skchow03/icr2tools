from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

from icr2_core.lp.binary import get_int32

LP_RECORD_SIZE_BYTES = 12
LP_RESOLUTION = 65536


def papy_speed_to_mph(speed_value: int) -> float:
    """Convert Papyrus internal speed units to miles per hour."""
    return speed_value * (15 / 1) * (3600 / 1) * (1 / 6000) * (1 / 5280)


@dataclass
class LpRecord:
    dlong: int
    speed_raw: int
    coriolis: int
    dlat: int

    @property
    def speed_mph(self) -> float:
        return papy_speed_to_mph(self.speed_raw)


@dataclass
class LpData:
    records: List[LpRecord]
    track_length: int | None = None

    @property
    def num_records(self) -> int:
        return len(self.records)

    def __iter__(self) -> Iterable[LpRecord]:
        return iter(self.records)


class LpFormatError(ValueError):
    """Raised when an LP file cannot be parsed."""


def _record_dlong(record_index: int, record_count: int, track_length: int | None) -> int:
    if track_length is None or record_index < record_count - 1:
        return record_index * LP_RESOLUTION
    return track_length


def _parse_lp_bytes(raw_bytes: bytes, track_length: int | None = None) -> LpData:
    if len(raw_bytes) < 4:
        raise LpFormatError("LP file too small to contain a record count")

    record_count = get_int32(raw_bytes, 0)
    expected_size = 4 + record_count * LP_RECORD_SIZE_BYTES
    if len(raw_bytes) < expected_size:
        raise LpFormatError(
            f"LP file is truncated: expected {expected_size} bytes for "
            f"{record_count} records, found {len(raw_bytes)}"
        )

    records: List[LpRecord] = []
    for record_index in range(record_count):
        offset = 4 + record_index * LP_RECORD_SIZE_BYTES
        speed_raw = get_int32(raw_bytes, offset)
        coriolis = get_int32(raw_bytes, offset + 4)
        dlat = get_int32(raw_bytes, offset + 8)
        dlong = _record_dlong(record_index, record_count, track_length)
        records.append(LpRecord(dlong=dlong, speed_raw=speed_raw, coriolis=coriolis, dlat=dlat))

    return LpData(records=records, track_length=track_length)


def load_lp_file(path: Path | str, *, track_length: int | None = None) -> LpData:
    """Load LP data from disk.

    Parameters
    ----------
    path:
        Path to the ``.LP`` file.
    track_length:
        Optional total track length used to set the final record's DLONG. If not
        provided, DLONG values are spaced by ``LP_RESOLUTION``.
    """

    raw_bytes = Path(path).read_bytes()
    return _parse_lp_bytes(raw_bytes, track_length=track_length)


def records_to_rows(records: Sequence[LpRecord]) -> List[tuple[int, float, int, int]]:
    """Return records as rows suitable for CSV output."""

    rows: List[tuple[int, float, int, int]] = []
    for record in records:
        rows.append((record.dlong, record.speed_mph, record.coriolis, record.dlat))
    return rows

