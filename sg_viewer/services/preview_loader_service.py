from __future__ import annotations

from pathlib import Path

from sg_viewer.services import preview_loader
from sg_viewer.models.sg_model import PreviewData


def load_preview(path: Path) -> PreviewData:
    return preview_loader.load_preview(path)
