"""Entry point for the ICR2 Track Viewer app."""

import os
import sys

from PyQt5 import QtWidgets

# Ensure repo root is on sys.path so icr2_core can be imported when packaged separately
if "icr2_core" not in sys.modules:
    repo_root = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(repo_root)
    if parent not in sys.path:
        sys.path.append(parent)

from .window import TrackViewerWindow


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("ICR2 Track Viewer")

    window = TrackViewerWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":  # pragma: no cover - handled by __main__
    main()
