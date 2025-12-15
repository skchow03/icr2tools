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
            "Optional log file path. Defaults to sg_viewer_log.txt next to the "
            "executable."
        ),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Shortcut for --log-level DEBUG",
    )
    return parser.parse_args(argv)


def configure_logging(log_level_name: str, log_path: str | None) -> str:
    resolved_level_name = log_level_name.upper()
    log_level = getattr(logging, resolved_level_name, logging.INFO)

    if not log_path:
        base_dir = os.path.dirname(sys.argv[0])
        log_path = os.path.join(base_dir, "sg_viewer_log.txt")

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path, mode="a", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    return log_path


def main() -> None:
    args = parse_args()
    log_level_name = "DEBUG" if args.debug else args.log_level
    log_path = configure_logging(log_level_name, args.log_file)
    logger.info("Starting SG Viewer (log level %s, log file %s)", log_level_name.upper(), log_path)

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
