"""UI loader helpers for Qt Designer assets."""
from __future__ import annotations

from pathlib import Path

from PyQt5 import uic


def load_ui(widget, filename: str) -> None:
    """Load a Qt Designer .ui file into the provided widget."""
    ui_path = Path(__file__).resolve().parent / "ui" / filename
    uic.loadUi(str(ui_path), widget)
