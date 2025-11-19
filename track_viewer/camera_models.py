"""Shared data structures for camera listings in the track viewer."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class CameraViewEntry:
    """Single camera reference within a TV view listing."""

    camera_index: int
    camera_type: Optional[int]
    start_dlong: Optional[int]
    end_dlong: Optional[int]
    mark: Optional[int] = None


@dataclass
class CameraViewListing:
    """Collection of camera entries for a specific TV mode."""

    label: str
    entries: List[CameraViewEntry]
