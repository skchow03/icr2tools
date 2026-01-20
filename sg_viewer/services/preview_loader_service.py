from __future__ import annotations

from pathlib import Path

from icr2_core.trk.sg_classes import SGFile
from sg_viewer.services import preview_loader
from sg_viewer.models.sg_model import PreviewData


def load_preview(path: Path) -> PreviewData:
    return preview_loader.load_preview(path)


def load_preview_from_sgfile(
    sgfile: SGFile,
    *,
    status_message: str,
) -> PreviewData:
    return preview_loader.load_preview_from_sgfile(sgfile, status_message=status_message)


def enable_trk_overlay(preview: PreviewData) -> None:
    preview_loader.enable_trk_overlay(preview)
