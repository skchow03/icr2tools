"""Entry point for the standalone ICR2 Track Viewer."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import sys

# ensure repo root on path for local runs
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from track_viewer.widget.app import TrackViewerWindow  # noqa: E402
from track_viewer.widget.track_viewer_app import TrackViewerApp  # noqa: E402


logger = logging.getLogger(__name__)


def configure_logging() -> None:
    base_dir = os.path.dirname(sys.argv[0])
    log_path = os.path.join(base_dir, "track_viewer_log.txt")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path, mode="a", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def main() -> None:
    configure_logging()
    logger.info("Starting ICR2 Track Viewer")

    app = TrackViewerApp(sys.argv, main_script_path=Path(__file__).resolve())

    window = TrackViewerWindow(app)
    window.show()

    def cleanup():
        try:
            if window:
                window.close()
        except Exception:  # pragma: no cover - best effort
            logger.exception("Unexpected error while closing window")

    app.aboutToQuit.connect(cleanup)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
