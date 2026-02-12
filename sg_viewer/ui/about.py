from __future__ import annotations

from PyQt5 import QtWidgets

from sg_viewer.version import __version__

ABOUT_DIALOG_TITLE = "About SG CREATE"

# Keep this HTML simple and easy to edit for future copy/style updates.
ABOUT_DIALOG_HTML_TEMPLATE = """
<div style="line-height: 1.45;">
  <h3 style="margin: 0 0 8px 0;">SG Circuit Rendering, Elevation And Track Editor (SG CREATE)</h3>
  <p style="margin: 0 0 8px 0;">Version: <b>{version}</b></p>
  <p style="margin: 0;">By SK Chow (aka Checkpoint10 on the icr2.net forums)</p>
</div>
""".strip()


def about_dialog_html() -> str:
    """Build rich-text content for the Help > About dialog."""
    return ABOUT_DIALOG_HTML_TEMPLATE.format(version=__version__)


def show_about_dialog(parent: QtWidgets.QWidget) -> None:
    """Display the About dialog for SG Viewer."""
    QtWidgets.QMessageBox.about(parent, ABOUT_DIALOG_TITLE, about_dialog_html())

