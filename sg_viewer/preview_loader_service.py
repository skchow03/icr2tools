from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from icr2_core.trk.sg_classes import SGFile
from icr2_core.trk.trk_classes import TRKFile
from track_viewer.geometry import CenterlineIndex

from sg_viewer import preview_loader

Point = Tuple[float, float]


@dataclass(frozen=True)
class PreviewLoadResult:
    sgfile: SGFile
    trk: TRKFile
    cline: List[Point]
    sampled_centerline: List[Point]
    sampled_dlongs: List[float]
    sampled_bounds: tuple[float, float, float, float]
    centerline_index: CenterlineIndex
    track_length: float
    start_finish_mapping: tuple[Point, Point, Point] | None
    sections: list[preview_loader.SectionPreview]
    section_endpoints: list[tuple[Point, Point]]
    status_message: str


def load_preview(path: Path) -> PreviewLoadResult:
    data = preview_loader.load_preview(path)
    return PreviewLoadResult(
        sgfile=data.sgfile,
        trk=data.trk,
        cline=data.cline,
        sampled_centerline=data.sampled_centerline,
        sampled_dlongs=data.sampled_dlongs,
        sampled_bounds=data.sampled_bounds,
        centerline_index=data.centerline_index,
        track_length=data.track_length,
        start_finish_mapping=data.start_finish_mapping,
        sections=data.sections,
        section_endpoints=data.section_endpoints,
        status_message=data.status_message,
    )
