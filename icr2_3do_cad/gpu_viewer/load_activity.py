"""Thread-safe, immediately persisted load trace for diagnosing stalled GPU loads.

The active file is overwritten only when a new explicit model load begins.
Worker threads write messages before potentially expensive calls; this is
independent of queued Qt progress updates, which may stop during GL upload.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Lock
from time import perf_counter


DEFAULT_LOAD_LOG = Path.home() / "ICR2Tools" / "gpu_viewer_last_load.log"


class LoadActivityTrace:
    def __init__(self, path=DEFAULT_LOAD_LOG):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")
        self._lock = Lock()
        self._start = perf_counter()

    def write(self, message):
        """Append one timestamped line on disk and return it for the UI."""
        stamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
        with self._lock:
            elapsed = perf_counter() - self._start
            line = f"[{stamp}] [+{elapsed:.3f}s] {message}"
            # Closing every append makes the latest BEGIN line available even
            # when the Qt GUI thread subsequently freezes in a driver call.
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            return line
