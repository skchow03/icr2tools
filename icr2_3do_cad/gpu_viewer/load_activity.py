"""Thread-safe, immediately persisted load trace for diagnosing stalled GPU loads.

The active file is overwritten only when a new explicit model load begins.
Worker threads write messages before potentially expensive calls; this is
independent of queued Qt progress updates, which may stop during GL upload.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Event, Lock, Thread, enumerate as all_threads
from time import perf_counter
import sys
import traceback


DEFAULT_LOAD_LOG = Path.home() / "ICR2Tools" / "gpu_viewer_last_load.log"


class LoadActivityTrace:
    def __init__(self, path=DEFAULT_LOAD_LOG):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")
        self._lock = Lock()
        self._start = perf_counter()
        self._last_activity = self._start
        self._last_message = 'Trace initialized'
        self._stop = Event()
        self._watchdog = None

    def write(self, message, *, activity=True):
        """Append one timestamped line on disk and return it for the UI."""
        stamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
        with self._lock:
            now = perf_counter()
            elapsed = now - self._start
            line = f"[{stamp}] [+{elapsed:.3f}s] {message}"
            if activity:
                self._last_activity = now
                self._last_message = str(message)
            # Closing every append makes the latest BEGIN line available even
            # when the Qt GUI thread subsequently freezes in a driver call.
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            return line

    def start_watchdog(self, *, quiet_seconds=12.0, repeat_seconds=20.0):
        """Write bounded Python stack snapshots when a load stops reporting.

        Does not invoke Qt. Remains able to record during GUI/GL blockage as
        long as Python can schedule another thread. Silence is not proof of
        a deadlock; the stacks are a diagnostic snapshot only.
        """
        if self._watchdog is not None:
            return

        def watch():
            last_snapshot = 0.0
            snapshots = 0
            while not self._stop.wait(1.0):
                with self._lock:
                    quiet = perf_counter() - self._last_activity
                    last = self._last_message
                if (quiet < quiet_seconds or
                        perf_counter() - last_snapshot < repeat_seconds or
                        snapshots >= 20):
                    continue
                last_snapshot = perf_counter()
                snapshots += 1
                try:
                    self.write(
                        f"INACTIVITY SNAPSHOT {snapshots}: no load event for "
                        f"{quiet:.1f}s; last operation: {last}",
                        activity=False)
                    names = {thread.ident: thread.name for thread in all_threads()}
                    for thread_id, frame in list(sys._current_frames().items())[:12]:
                        if thread_id == self._watchdog.ident:
                            continue
                        self.write(
                            f"PYTHON THREAD {thread_id} "
                            f"({names.get(thread_id, 'unnamed')}):",
                            activity=False)
                        for line in traceback.format_stack(frame, limit=16):
                            for part in line.rstrip().splitlines():
                                self.write(f"  {part}", activity=False)
                except OSError:
                    return

        self._watchdog = Thread(
            target=watch, name="ICR2LoadActivityWatchdog", daemon=True)
        self._watchdog.start()

    def stop_watchdog(self):
        self._stop.set()
