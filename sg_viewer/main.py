"""Entry point for the SG viewer."""

import argparse
import logging
import os
import sys

# ensure repo root on path for local runs
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from sg_viewer.ui.app import SGViewerApp, SGViewerWindow  # noqa: E402

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SG viewer")
    parser.add_argument(
        "--log-level",
        default=os.getenv("SG_VIEWER_LOG_LEVEL", "INFO"),
        help=(
            "Logging level (e.g. DEBUG, INFO). Defaults to SG_VIEWER_LOG_LEVEL "
            "environment variable or INFO."
        ),
    )
    parser.add_argument(
        "--log-file",
        default=os.getenv("SG_VIEWER_LOG_PATH"),
        help=(
            "Deprecated. SG viewer no longer writes logs to file and this "
            "option is ignored."
        ),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Shortcut for --log-level DEBUG",
    )
    return parser.parse_args(argv)


def configure_logging(log_level_name: str, log_path: str | None) -> None:
    resolved_level_name = log_level_name.upper()
    log_level = getattr(logging, resolved_level_name, logging.INFO)

    if log_path:
        logger.warning("Ignoring --log-file; SG viewer no longer writes a log file")

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def main() -> None:
    args = parse_args()
    log_level_name = "DEBUG" if args.debug else args.log_level
    configure_logging(log_level_name, args.log_file)
    logger.info("Starting SG Viewer (log level %s)", log_level_name.upper())

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
