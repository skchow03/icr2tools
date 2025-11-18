"""
main.py

Entry point: starts the control panel and wires it to the updater.
"""
import logging, os, sys
# add parent folder (ICR2Tools) to Python path so icr2_core can be found
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from collections import deque
from PyQt5 import QtWidgets, QtCore
from icr2_core.icr2_memory import ICR2Memory, WindowNotFoundError
from icr2timing.core.config import Config
from icr2_core.reader import MemoryReader
from icr2timing.updater.updater import RaceUpdater
from icr2timing.ui.control_panel import ControlPanel
from icr2timing.core.version import __version__
from PyQt5.QtGui import QIcon

base_dir = os.path.dirname(sys.argv[0])
log_path = os.path.join(base_dir, "timing_log.txt")


class CappedFileHandler(logging.FileHandler):
    """A FileHandler that keeps only the last N lines of logs."""
    def __init__(self, filename, max_lines=200, mode="a", encoding="utf-8"):
        super().__init__(filename, mode=mode, encoding=encoding)
        self.max_lines = max_lines
        self._buffer = deque(maxlen=max_lines)

    def emit(self, record):
        msg = self.format(record)
        self._buffer.append(msg + "\n")
        # Flush buffer to file every 10 lines or on error
        if len(self._buffer) % 10 == 0 or record.levelno >= logging.ERROR:
            with open(self.baseFilename, "w", encoding=self.encoding) as f:
                f.writelines(self._buffer)


# --- Configure global logger ---
log_handler = CappedFileHandler(log_path, max_lines=200)
stream_handler = logging.StreamHandler(sys.stdout)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[log_handler, stream_handler],
)

logging.getLogger(__name__).info(f"Starting ICR2 Timing Overlay {__version__}")



def main():
    app = QtWidgets.QApplication(sys.argv)
    
    # ✅ Set icon path (works for both dev & frozen .exe)
    if getattr(sys, 'frozen', False):
        basedir = sys._MEIPASS
    else:
        basedir = os.path.dirname(__file__)

    icon_path = os.path.join(basedir, "assets", "icon.ico")
    app.setWindowIcon(QIcon(icon_path))


    app.setQuitOnLastWindowClosed(True)

    cfg = Config.current()
    mem = None

    # --- Retry loop ---
    while mem is None:
        try:
            mem = ICR2Memory(verbose=False)
        except WindowNotFoundError as e:
            reply = QtWidgets.QMessageBox.critical(
                None,
                "ICR2 Timing Overlay",
                str(e),
                QtWidgets.QMessageBox.Retry | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.Retry,
            )
            if reply == QtWidgets.QMessageBox.Cancel:
                sys.exit(1)
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                None,
                "ICR2 Timing Overlay",
                f"Unexpected error: {e}"
            )
            sys.exit(1)

    reader = MemoryReader(mem, cfg)
    updater = RaceUpdater(reader, poll_ms=cfg.poll_ms)

    # Thread for updater
    thread = QtCore.QThread()
    updater.moveToThread(thread)

    shutdown_done = False

    def stop_worker_thread():
        nonlocal shutdown_done
        if shutdown_done:
            return
        shutdown_done = True
        try:
            if updater:
                QtCore.QMetaObject.invokeMethod(
                    updater, "stop", QtCore.Qt.BlockingQueuedConnection
                )
        except Exception:
            pass
        try:
            if thread.isRunning():
                thread.quit()
                if not thread.wait(2000):
                    print("Warning: Worker thread did not stop cleanly")
                    thread.terminate()
                    thread.wait(1000)
        except Exception:
            pass

    # Control panel (owns overlay + signal wiring)
    panel = ControlPanel(updater, mem=mem, cfg=cfg, shutdown_hook=stop_worker_thread)
    panel.show()

    def cleanup():
        stop_worker_thread()
        try:
            mem.close()
        except Exception:
            pass

    app.aboutToQuit.connect(cleanup)

    thread.start()
    QtCore.QMetaObject.invokeMethod(updater, "start", QtCore.Qt.QueuedConnection)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
