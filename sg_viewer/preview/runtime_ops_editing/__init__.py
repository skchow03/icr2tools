from __future__ import annotations

from sg_viewer.preview.runtime_ops_editing.edit_commit_adapter import (
    _RuntimeEditCommitAdapterMixin,
)
from sg_viewer.preview.runtime_ops_editing.edit_constraints import (
    _RuntimeEditConstraintsMixin,
)
from sg_viewer.preview.runtime_ops_editing.edit_preview_ops import (
    _RuntimeEditPreviewOpsMixin,
)


class _RuntimeEditingMixin(
    _RuntimeEditPreviewOpsMixin,
    _RuntimeEditConstraintsMixin,
    _RuntimeEditCommitAdapterMixin,
):
    pass
