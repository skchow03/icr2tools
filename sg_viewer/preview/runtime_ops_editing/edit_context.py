from __future__ import annotations

from dataclasses import dataclass

from sg_viewer.models.sg_model import SectionPreview
from sg_viewer.preview.runtime_ops_core import Point


@dataclass(frozen=True)
class EditContext:
    sections: tuple[SectionPreview, ...]
    track_length: float | None
    start_finish_dlong: float | None
    centerline_index: int | None
    sampled_dlongs: tuple[float, ...]
    sampled_centerline: tuple[Point, ...]


def capture_edit_context(
    sections: list[SectionPreview],
    *,
    track_length: float | None,
    start_finish_dlong: float | None,
    centerline_index: int | None,
    sampled_dlongs: list[float],
    sampled_centerline: list[Point],
) -> EditContext:
    return EditContext(
        sections=tuple(sections),
        track_length=track_length,
        start_finish_dlong=start_finish_dlong,
        centerline_index=centerline_index,
        sampled_dlongs=tuple(sampled_dlongs),
        sampled_centerline=tuple(sampled_centerline),
    )
