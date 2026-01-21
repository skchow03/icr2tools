from __future__ import annotations
from dataclasses import dataclass, replace
from typing import List, Tuple

from icr2_core.trk.sg_classes import SGFile
from icr2_core.trk.trk_classes import TRKFile
from sg_viewer.models.preview_fsection import PreviewFSection

Point = Tuple[float, float]


@dataclass(frozen=True)
class SectionPreview:
    section_id: int
    type_name: str
    previous_id: int
    next_id: int
    start: Point
    end: Point
    start_dlong: float
    length: float
    center: Point | None
    sang1: float | None
    sang2: float | None
    eang1: float | None
    eang2: float | None
    radius: float | None
    start_heading: tuple[float, float] | None
    end_heading: tuple[float, float] | None
    polyline: List[Point]
    start_dlat: float = 0.0
    end_dlat: float = 0.0


@dataclass(frozen=True)
class PreviewData:
    sg: SGFile
    sgfile: SGFile
    # NOTE: trk is optional.
    # SG Viewer preview must function without TRK.
    trk: TRKFile | None
    cline: List[Point] | None
    sampled_centerline: List[Point]
    sampled_dlongs: List[float]
    sampled_bounds: tuple[float, float, float, float]
    centerline_index: object
    track_length: float
    start_finish_mapping: tuple[Point, Point, Point] | None
    sections: List[SectionPreview]
    section_endpoints: List[tuple[Point, Point]]
    fsections: List[PreviewFSection]
    status_message: str
