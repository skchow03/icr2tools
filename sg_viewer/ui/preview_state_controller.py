from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import List, Tuple

from PyQt5 import QtCore

from icr2_core.trk.sg_classes import SGFile
from icr2_core.trk.trk_classes import TRKFile
from sg_viewer.geometry import preview_transform
from sg_viewer.models import preview_state
from sg_viewer.services import preview_loader_service

Point = Tuple[float, float]
Transform = tuple[float, tuple[float, float]]


class PreviewStateController:
    def __init__(self) -> None:
        self._sgfile: SGFile | None = None
        self._trk: TRKFile | None = None
        self._sampled_centerline: List[Point] = []
        self._sampled_bounds: tuple[float, float, float, float] | None = None
        self._track_length: float | None = None
        self._transform_state = preview_state.TransformState()
        self._status_message = "Select an SG file to begin."

    # ------------------------------------------------------------------
    # Core data
    # ------------------------------------------------------------------
    @property
    def sgfile(self) -> SGFile | None:
        return self._sgfile

    @sgfile.setter
    def sgfile(self, value: SGFile | None) -> None:
        self._sgfile = value

    @property
    def trk(self) -> TRKFile | None:
        return self._trk

    @trk.setter
    def trk(self, value: TRKFile | None) -> None:
        self._trk = value

    @property
    def sampled_centerline(self) -> list[Point]:
        return self._sampled_centerline

    @sampled_centerline.setter
    def sampled_centerline(self, value: list[Point]) -> None:
        self._sampled_centerline = value

    @property
    def sampled_bounds(self) -> tuple[float, float, float, float] | None:
        return self._sampled_bounds

    @sampled_bounds.setter
    def sampled_bounds(self, value: tuple[float, float, float, float] | None) -> None:
        self._sampled_bounds = value

    @property
    def track_length(self) -> float | None:
        return self._track_length

    @track_length.setter
    def track_length(self, value: float | None) -> None:
        self._track_length = value

    @property
    def status_message(self) -> str:
        return self._status_message

    @status_message.setter
    def status_message(self, value: str) -> None:
        self._status_message = value

    # ------------------------------------------------------------------
    # Transform state
    # ------------------------------------------------------------------
    @property
    def transform_state(self) -> preview_state.TransformState:
        return self._transform_state

    @transform_state.setter
    def transform_state(self, value: preview_state.TransformState) -> None:
        self._transform_state = value

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------
    def clear(self, message: str | None = None) -> None:
        self._sgfile = None
        self._trk = None
        self._sampled_centerline = []
        self._sampled_bounds = None
        self._track_length = None
        self._transform_state = preview_state.TransformState()
        self._status_message = message or "Select an SG file to begin."

    def load_sg_file(self, path: Path) -> preview_loader_service.PreviewData | None:
        if not path:
            self.clear()
            return None

        self._status_message = f"Loading {path.name}…"
        data = preview_loader_service.load_preview(path)

        self._sgfile = data.sgfile
        self._trk = data.trk
        self._sampled_centerline = data.sampled_centerline
        self._sampled_bounds = data.sampled_bounds
        self._track_length = data.track_length
        self._transform_state = preview_state.TransformState()
        self._status_message = data.status_message
        return data

    # ------------------------------------------------------------------
    # Transform helpers
    # ------------------------------------------------------------------
    def default_center(self) -> Point | None:
        return preview_state.default_center(
            preview_transform.apply_default_bounds(self._sampled_bounds)
        )

    def update_fit_scale(self, widget_size: tuple[int, int]) -> preview_state.TransformState:
        self._transform_state = preview_transform.update_fit_scale(
            self._transform_state, self._sampled_bounds, widget_size
        )
        return self._transform_state

    def current_transform(self, widget_size: tuple[int, int]) -> Transform | None:
        transform, updated_state = preview_transform.current_transform(
            self._transform_state, self._sampled_bounds, widget_size
        )
        if updated_state is not self._transform_state:
            self._transform_state = updated_state
        return transform

    def clamp_scale(self, scale: float) -> float:
        return preview_state.clamp_scale(scale, self._transform_state)

    def map_to_track(
        self,
        point: QtCore.QPointF,
        widget_size: tuple[int, int],
        widget_height: int,
        transform: Transform | None = None,
    ) -> Point | None:
        active_transform = transform or self.current_transform(widget_size)
        return preview_state.map_to_track(active_transform, (point.x(), point.y()), widget_height)

    def update_transform_state(self, **kwargs) -> None:
        self._transform_state = replace(self._transform_state, **kwargs)
