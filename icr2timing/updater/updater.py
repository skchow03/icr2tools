"""
updater.py

RaceUpdater runs in a worker QThread and polls MemoryReader periodically.
It emits `state_updated` (RaceState) and `error` (str).

Fixed to properly handle timer cleanup in the correct thread.
"""

from PyQt5 import QtCore
from typing import Optional

from icr2_core.reader import MemoryReader, ReadError
from icr2_core.model import RaceState



class RaceUpdater(QtCore.QObject):
    """
    RaceUpdater polls MemoryReader and emits RaceState objects.

    Usage:
      - create MemoryReader and RaceUpdater(reader, poll_ms)
      - create QThread, move updater to thread, start thread, invoke start()
      - connect signals: state_updated (RaceState), error (str)
      - call stop() (via QMetaObject.invokeMethod) before quitting thread
    """
    state_updated = QtCore.pyqtSignal(object)  # RaceState
    error = QtCore.pyqtSignal(str)

    def __init__(self, reader: MemoryReader, poll_ms: int = 250):
        super().__init__()
        self._reader = reader
        self._poll_ms = max(20, int(poll_ms))
        self._timer: Optional[QtCore.QTimer] = None
        self._running = False

    @QtCore.pyqtSlot()
    def start(self):
        """Called in the worker thread; starts a QTimer in that thread's event loop."""
        if self._running:
            return
        self._running = True
        self._timer = QtCore.QTimer()
        self._timer.setTimerType(QtCore.Qt.PreciseTimer)  # <-- use high-precision timer
        self._timer.setInterval(self._poll_ms)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()


    @QtCore.pyqtSlot()
    def stop(self):
        """Stop polling and quit the worker's event loop (thread owner should quit thread)."""
        self._running = False
        if self._timer is not None:
            try:
                self._timer.stop()
                self._timer.deleteLater()  # Schedule for deletion in correct thread
            except Exception:
                pass
            self._timer = None

    @QtCore.pyqtSlot(int)
    def set_poll_interval(self, ms: int):
        """Adjust polling rate dynamically."""
        ms = max(20, int(ms))
        self._poll_ms = ms
        if self._timer is not None:
            self._timer.setInterval(self._poll_ms)


    def __del__(self):
        """Destructor - ensure timer is properly cleaned up."""
        # Don't try to stop timer here, just set it to None
        # The timer should have been stopped by stop() method
        self._timer = None

    def _on_tick(self):
        """Tick handler invoked in worker thread; read state and emit results."""
        if not self._running:  # Extra safety check
            return
            
        try:
            state = self._reader.read_race_state()
            # emit to main thread
            self.state_updated.emit(state)
        except ReadError as re:
            # Required read failed; bubble up as error (persistent)
            self.error.emit(str(re))
        except Exception as e:
            # Unexpected errors: emit but keep polling
            self.error.emit(f"{type(e).__name__}: {e}")