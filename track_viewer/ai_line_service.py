"""Services for loading AI line (LP) data for track previews."""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from PyQt5 import QtCore

from icr2_core.lp.loader import load_lp_file
from icr2_core.trk.trk_classes import TRKFile
from icr2_core.trk.trk_utils import getxyz


@dataclass
class LpPoint:
    x: float
    y: float
    dlong: float
    dlat: float
    speed_raw: int
    speed_mph: float
    lateral_speed: float
    angle_deg: float | None = None


def _normalize_angle(angle: float) -> float:
    while angle <= -math.pi:
        angle += 2 * math.pi
    while angle > math.pi:
        angle -= 2 * math.pi
    return angle


def _centerline_heading(
    trk: TRKFile,
    cline: list[tuple[float, float]],
    dlong: float,
    track_length: float,
    *,
    delta: float = 1.0,
) -> float | None:
    if track_length <= 0:
        return None
    prev_dlong = dlong - delta
    next_dlong = dlong + delta
    if prev_dlong < 0:
        prev_dlong += track_length
    if next_dlong > track_length:
        next_dlong -= track_length
    prev_x, prev_y, _ = getxyz(trk, prev_dlong, 0, cline)
    next_x, next_y, _ = getxyz(trk, next_dlong, 0, cline)
    dx = next_x - prev_x
    dy = next_y - prev_y
    if dx == 0 and dy == 0:
        return None
    return math.atan2(dy, dx)


def load_ai_line_records(
    trk: TRKFile | None,
    cline: list[tuple[float, float]],
    track_path: Path | None,
    track_length: float | None,
    lp_name: str,
) -> list[LpPoint]:
    if trk is None or not cline or track_path is None:
        return []

    lp_path = track_path / f"{lp_name}.LP"
    if not lp_path.exists():
        return []

    length_arg = int(track_length) if track_length is not None else None
    try:
        ai_line = load_lp_file(lp_path, track_length=length_arg)
    except Exception:
        return []

    points: list[LpPoint] = []
    for record in ai_line:
        try:
            x, y, _ = getxyz(trk, float(record.dlong), record.dlat, cline)
        except Exception:
            continue
        points.append(
            LpPoint(
                x=x,
                y=y,
                dlong=float(record.dlong),
                dlat=float(record.dlat),
                speed_raw=int(record.speed_raw),
                speed_mph=float(record.speed_mph),
                lateral_speed=float(record.coriolis),
            )
        )
    if len(points) < 2:
        return points

    track_length_value = float(track_length or trk.trklength or 0.0)
    if track_length_value <= 0:
        return points
    for index, record in enumerate(points):
        prev_record = points[index - 1]
        next_record = points[(index + 1) % len(points)]
        dx = next_record.x - prev_record.x
        dy = next_record.y - prev_record.y
        if dx == 0 and dy == 0:
            continue
        lp_heading = math.atan2(dy, dx)
        centerline_heading = _centerline_heading(
            trk,
            cline,
            record.dlong,
            track_length_value,
        )
        if centerline_heading is None:
            continue
        record.angle_deg = math.degrees(
            _normalize_angle(lp_heading - centerline_heading)
        )
    return points


class AiLineLoadSignals(QtCore.QObject):
    loaded = QtCore.pyqtSignal(int, str, list)


class AiLineLoadTask(QtCore.QRunnable):
    def __init__(
        self,
        generation: int,
        lp_name: str,
        trk: TRKFile | None,
        cline: list[tuple[float, float]],
        track_path: Path | None,
        track_length: float | None,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.signals = AiLineLoadSignals()
        self._generation = generation
        self._lp_name = lp_name
        self._trk = trk
        self._cline = cline
        self._track_path = track_path
        self._track_length = track_length

    def run(self) -> None:
        records = load_ai_line_records(
            self._trk,
            self._cline,
            self._track_path,
            self._track_length,
            self._lp_name,
        )
        self.signals.loaded.emit(self._generation, self._lp_name, records)
