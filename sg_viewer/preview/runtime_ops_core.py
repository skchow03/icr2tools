from __future__ import annotations

from sg_viewer.preview.runtime_ops.base import Point, Transform, _RuntimeCoreBaseMixin
from sg_viewer.preview.runtime_ops.commit_ops import _RuntimeCoreCommitOpsMixin
from sg_viewer.preview.runtime_ops.connect_ops import _RuntimeCoreConnectOpsMixin
from sg_viewer.preview.runtime_ops.drag_node import _RuntimeCoreDragNodeMixin
from sg_viewer.preview.runtime_ops.drag_polyline import _RuntimeCoreDragPolylineMixin


class _RuntimeCoreMixin(
    _RuntimeCoreBaseMixin,
    _RuntimeCoreCommitOpsMixin,
    _RuntimeCoreConnectOpsMixin,
    _RuntimeCoreDragNodeMixin,
    _RuntimeCoreDragPolylineMixin,
):
    pass


__all__ = ["Point", "Transform", "_RuntimeCoreMixin"]
