from __future__ import annotations

from pathlib import Path

from icr2_core.trk.sg_classes import SGFile
from sg_viewer.models.sg_model import PreviewData
from sg_viewer.services import preview_loader


def load_preview(path: Path) -> PreviewData:
    return preview_loader.load_preview(path)


def load_preview_from_sgfile(sgfile: SGFile) -> PreviewData:
    return preview_loader.load_preview_from_sgfile(sgfile)
