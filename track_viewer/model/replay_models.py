"""Replay model helpers."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReplayLapInfo:
    lap_number: int
    status: str
    frames: int
    time_text: str
    start_frame: int
    end_frame: int
