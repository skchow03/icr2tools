"""Stage-progress regressions for the GPU viewer (no proprietary 3DOs).

The worker signals coarse completed stages; percentages do not represent
elapsed-time estimates. UI tests require a display, like other GPU tests.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from gpu_viewer.load_activity import LoadActivityTrace

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or
                   os.environ.get("WAYLAND_DISPLAY") or
                   sys.platform in ("win32", "darwin"))

try:
    from gpu_viewer.main import LoadWorker, SourceExportWorker
    HAS_DEPS = True
except (ImportError, SystemExit):
    HAS_DEPS = False


SIMPLE_N3 = """3D VERSION 3.0;
a: [<0,0,0>];
b: [<1000,0,0>];
c: [<0,1000,0>];
p: POLY <44> {a,b,c};
root: LIST {p};
"""


@unittest.skipUnless(HAS_DEPS, "PySide6/OpenGL viewer dependencies required")
class LoadWorkerStageTests(unittest.TestCase):
    def test_worker_emits_ordered_stages_then_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "synthetic.3d"
            worker = LoadWorker(
                path, Path(__file__).resolve().parents[1] / "gamepal.pcx",
                source_text=SIMPLE_N3, source_path=path)
            stages, ready, errors = [], [], []
            worker.progress.connect(lambda number, label: stages.append((number, label)))
            worker.ready.connect(lambda *args: ready.append(args))
            worker.failed.connect(errors.append)
            # Execute directly for a deterministic CPU-only signal test.
            worker.run()
            self.assertFalse(errors, errors)
            self.assertEqual(len(ready), 1)
            numbers = [number for number, _ in stages]
            self.assertEqual(numbers, [5, 30, 42, 55, 63, 74, 85, 89])
            self.assertTrue(all(isinstance(label, str) and label
                                for _, label in stages))
            self.assertEqual(ready[0][0].polygon_count, 1)

    def test_worker_writes_detailed_log_before_scene_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "synthetic.3d"
            trace = LoadActivityTrace(Path(temp) / "activity.log")
            worker = LoadWorker(
                path, Path(__file__).resolve().parents[1] / "gamepal.pcx",
                source_text=SIMPLE_N3, source_path=path,
                activity_trace=trace)
            events = []
            worker.activity.connect(events.append)
            worker.run()
            contents = trace.path.read_text(encoding="utf-8")
            self.assertIn("Compiling N3 source", contents)
            self.assertIn("Walking referenced scene graph", contents)
            self.assertIn("Packing mesh", contents)
            self.assertIn("handing scene to Qt GUI thread", contents)
            self.assertEqual(len(events), len(contents.splitlines()))

    def test_editable_source_export_reports_substeps(self):
        from n3_compile import compile_n3_text
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "synthetic.3d"
            model, _ = compile_n3_text(SIMPLE_N3, path,
                                       associate_planes=False)
            trace = LoadActivityTrace(Path(temp) / "source.log")
            worker = SourceExportWorker(
                model, path.with_suffix(".3do"), activity_trace=trace)
            results, errors = [], []
            worker.ready.connect(lambda text, target: results.append(text))
            worker.failed.connect(errors.append)
            worker.run()
            self.assertFalse(errors, errors)
            self.assertEqual(len(results), 1)
            self.assertIn("3D VERSION 3.0", results[0])
            output = trace.path.read_text(encoding="utf-8")
            self.assertIn("Editable source BEGIN", output)
            self.assertIn("Editable source: record", output)
            self.assertIn("Editable source DONE", output)

    def test_worker_failure_reports_error_not_readiness(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "invalid.3d"
            worker = LoadWorker(path, path / "missing.pcx",
                                source_text="3D VERSION 3.0;\ninvalid",
                                source_path=path)
            stages, errors, ready = [], [], []
            worker.progress.connect(lambda number, label: stages.append(number))
            worker.failed.connect(errors.append)
            worker.ready.connect(lambda *args: ready.append(args))
            worker.run()
            self.assertEqual(stages, [5])
            self.assertEqual(len(errors), 1)
            self.assertFalse(ready)


@unittest.skipUnless(HAS_DEPS and HAS_DISPLAY, "Qt desktop or Xvfb required")
class LoadProgressUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from gpu_viewer.main import Window
        cls.app = QApplication.instance() or QApplication([])
        cls.window = Window()
        cls.window.show()
        cls.app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.window.close()

    def test_in_viewport_stage_changes_and_failure_reset(self):
        win = self.window
        marker = object()
        win._begin_load_progress(marker)
        self.assertFalse(win.load_progress.isHidden())
        self.assertEqual(win.load_progress.value(), 0)
        win._load_progress_stage(marker, 63, "Decoding PMP sprites")
        self.assertEqual(win.load_progress.value(), 63)
        self.assertIn("Decoding PMP sprites", win.load_progress.format())
        win._load_progress_stage(object(), 99, "Old worker")
        self.assertEqual(win.load_progress.value(), 63)
        win._end_load_progress(marker, success=False)
        self.assertTrue(win.load_progress.isHidden())
        self.assertIsNone(win._load_progress_worker)

    def test_live_dock_shows_current_and_persists_last_attempt(self):
        win = self.window
        previous = win.worker
        marker = SimpleNamespace(activity_trace=None)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "durable.log"
            with patch("gpu_viewer.main.LoadActivityTrace",
                       side_effect=lambda: LoadActivityTrace(path)):
                try:
                    win.worker = marker
                    win._begin_load_activity(marker)
                    self.assertFalse(win.load_activity_dock.isHidden())
                    self.assertEqual(marker.activity_trace.path, path)
                    win._record_load_activity("GPU upload BEGIN: geometry VBO")
                    self.assertIn("GPU upload BEGIN", path.read_text())
                    self.assertIn("GPU upload BEGIN",
                                  win.load_activity_text.toPlainText())
                    old = win.load_activity_text.toPlainText()
                    win._append_load_activity(object(), "stale data")
                    self.assertEqual(win.load_activity_text.toPlainText(), old)
                    self.assertIn("GPU upload BEGIN", win._full_load_activity_text())
                finally:
                    win.worker = previous
                    win._load_activity_worker = None
                    win._load_trace = None
                    win.load_activity_dock.hide()

    def test_completed_load_does_not_hide_newer_load(self):
        win = self.window
        old, new = object(), object()
        win._begin_load_progress(old)
        win._end_load_progress(old, success=True)
        self.assertEqual(win.load_progress.value(), 100)
        win._begin_load_progress(new)
        win._hide_completed_load_progress(old)
        self.assertFalse(win.load_progress.isHidden())
        self.assertEqual(win.load_progress.value(), 0)
        win._end_load_progress(new, success=False)


if __name__ == "__main__":
    unittest.main()
