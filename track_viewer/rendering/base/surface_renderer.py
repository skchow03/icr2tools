"""Surface and boundary rendering for the track preview."""
from __future__ import annotations

from PyQt5 import QtCore, QtGui

from track_viewer.model.track_preview_model import TrackPreviewModel
from track_viewer.model.view_state import TrackPreviewViewState
from track_viewer.rendering import build_boundary_path, build_surface_cache
from track_viewer.rendering.base.transform import surface_transform


class SurfaceRenderer:
    """Render surface mesh and boundary geometry with caching."""

    def __init__(self) -> None:
        self._surface_cache: list = []
        self._surface_cache_key: tuple[object | None, int] | None = None
        self._boundary_path_cache = QtGui.QPainterPath()
        self._boundary_cache_key: tuple[object | None, int] | None = None

    def invalidate_cache(self) -> None:
        self._surface_cache = []
        self._surface_cache_key = None
        self._boundary_path_cache = QtGui.QPainterPath()
        self._boundary_cache_key = None

    def draw(
        self,
        painter: QtGui.QPainter,
        model: TrackPreviewModel,
        state: TrackPreviewViewState,
        transform: tuple[float, tuple[float, float]],
        viewport_height: int,
    ) -> None:
        if not model.surface_mesh:
            return

        self._ensure_surface_cache(model)
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        painter.setTransform(surface_transform(transform, viewport_height))
        for surface in self._surface_cache:
            painter.setBrush(QtGui.QBrush(surface.fill))
            painter.setPen(QtGui.QPen(surface.outline, 1))
            painter.drawPolygon(surface.polygon)
        painter.restore()

        if not state.show_boundaries:
            return

        self._ensure_boundary_cache(model)
        if self._boundary_path_cache.isEmpty():
            return

        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        pen = QtGui.QPen(QtGui.QColor("lightgray"), 2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.setTransform(surface_transform(transform, viewport_height))
        painter.drawPath(self._boundary_path_cache)
        painter.restore()

    def _ensure_surface_cache(self, model: TrackPreviewModel) -> None:
        key = (model.track_path, id(model.surface_mesh))
        if key == self._surface_cache_key and self._surface_cache:
            return
        self._surface_cache = build_surface_cache(model.surface_mesh)
        self._surface_cache_key = key

    def _ensure_boundary_cache(self, model: TrackPreviewModel) -> None:
        key = (model.track_path, id(model.boundary_edges))
        if key == self._boundary_cache_key:
            return
        self._boundary_path_cache = build_boundary_path(model.boundary_edges)
        self._boundary_cache_key = key
