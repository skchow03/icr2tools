from __future__ import annotations

from pathlib import Path

from sg_viewer import preview_loader
from sg_viewer.sg_model import PreviewData


def load_preview(path: Path) -> PreviewData:
    return preview_loader.load_preview(path)
