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

    def build_runtime():
        local_cfg = Config()
        mem_obj = None
        while mem_obj is None:
            try:
                mem_obj = ICR2Memory(verbose=False)
            except WindowNotFoundError as e:
                reply = QtWidgets.QMessageBox.critical(
                    None,
                    "ICR2 Timing Overlay",
                    str(e),
                    QtWidgets.QMessageBox.Retry | QtWidgets.QMessageBox.Cancel,
                    QtWidgets.QMessageBox.Retry,
                )
                if reply == QtWidgets.QMessageBox.Cancel:
                    return None
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    None,
                    "ICR2 Timing Overlay",
                    f"Unexpected error: {e}"
                )
                return None

        reader_obj = MemoryReader(mem_obj, local_cfg)
        updater_obj = RaceUpdater(reader_obj, poll_ms=local_cfg.poll_ms)
        thread_obj = QtCore.QThread()
        updater_obj.moveToThread(thread_obj)
        return local_cfg, mem_obj, reader_obj, updater_obj, thread_obj

    def start_runtime(updater_obj, thread_obj):
        if not updater_obj or not thread_obj:
            return
        thread_obj.start()
        QtCore.QMetaObject.invokeMethod(updater_obj, "start", QtCore.Qt.QueuedConnection)

    def stop_runtime(updater_obj, thread_obj, mem_obj):
        try:
            if updater_obj and thread_obj and thread_obj.isRunning():
                QtCore.QMetaObject.invokeMethod(
                    updater_obj, "stop", QtCore.Qt.BlockingQueuedConnection
                )
        except Exception:
            pass
        try:
            if thread_obj and thread_obj.isRunning():
                thread_obj.quit()
                if not thread_obj.wait(2000):
                    logging.getLogger(__name__).warning(
                        "Worker thread did not stop cleanly; terminating"
                    )
                    thread_obj.terminate()
                    thread_obj.wait(1000)
        except Exception:
            pass
        try:
            if mem_obj:
                mem_obj.close()
        except Exception:
            pass

    runtime = build_runtime()
    if runtime is None:
        sys.exit(1)

    cfg, mem, reader, updater, thread = runtime

    panel = ControlPanel(updater, mem=mem, cfg=cfg)
    panel.show()

    # ensure panel knows about the worker thread
    panel.attach_runtime(updater, mem, cfg, thread)

    start_runtime(updater, thread)

    def handle_installation_switch(new_key: str, previous_key: str):
        nonlocal cfg, mem, reader, updater, thread

        new_runtime = build_runtime()
        if new_runtime is None:
            panel.revert_installation_switch(previous_key)
            return

        new_cfg, new_mem, new_reader, new_updater, new_thread = new_runtime

        panel.attach_runtime(new_updater, new_mem, new_cfg, new_thread)
        start_runtime(new_updater, new_thread)

        stop_runtime(updater, thread, mem)

        cfg, mem, reader, updater, thread = new_cfg, new_mem, new_reader, new_updater, new_thread
        panel.confirm_installation_switch(new_key)

    panel.installation_switch_requested.connect(handle_installation_switch)

    def cleanup():
        stop_runtime(updater, thread, mem)

    app.aboutToQuit.connect(cleanup)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
