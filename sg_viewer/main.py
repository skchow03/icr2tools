"""Entry point for the SG viewer."""

import logging
import os
import sys

# ensure repo root on path for local runs
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from sg_viewer.app import SGViewerApp, SGViewerWindow  # noqa: E402

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    base_dir = os.path.dirname(sys.argv[0])
    log_path = os.path.join(base_dir, "sg_viewer_log.txt")

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
    logger.info("Starting SG Viewer")

    app = SGViewerApp(sys.argv)
    window = SGViewerWindow()
    app.window = window
    window.show()

    def cleanup() -> None:
        try:
            if window:
                window.close()
        except Exception:  # pragma: no cover - best effort
            logger.exception("Unexpected error while closing window")

    app.aboutToQuit.connect(cleanup)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
