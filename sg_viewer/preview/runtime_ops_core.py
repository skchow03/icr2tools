from __future__ import annotations

from sg_viewer.preview.runtime_ops.base_context import Point, Transform
from sg_viewer.preview.runtime_ops.op_base import _RuntimeCoreBaseMixin
from sg_viewer.preview.runtime_ops.op_commit import _RuntimeCoreCommitMixin
from sg_viewer.preview.runtime_ops.op_preview import _RuntimeCorePreviewMixin
from sg_viewer.preview.runtime_ops.op_validation import _RuntimeCoreValidationMixin
from sg_viewer.preview.runtime_ops.commit_ops import _RuntimeCoreCommitOpsMixin
from sg_viewer.preview.runtime_ops.connect_ops import _RuntimeCoreConnectOpsMixin
from sg_viewer.preview.runtime_ops.drag_node import _RuntimeCoreDragNodeMixin
from sg_viewer.preview.runtime_ops.drag_polyline import _RuntimeCoreDragPolylineMixin


class _RuntimeCoreMixin(
    _RuntimeCoreBaseMixin,
    _RuntimeCoreValidationMixin,
    _RuntimeCoreCommitMixin,
    _RuntimeCorePreviewMixin,
    _RuntimeCoreCommitOpsMixin,
    _RuntimeCoreConnectOpsMixin,
    _RuntimeCoreDragNodeMixin,
    _RuntimeCoreDragPolylineMixin,
):
    pass


__all__ = ["Point", "Transform", "_RuntimeCoreMixin"]
