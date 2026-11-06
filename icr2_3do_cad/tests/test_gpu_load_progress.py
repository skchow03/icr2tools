"""Stage-progress regressions for the GPU viewer (no proprietary 3DOs).

The worker signals coarse completed stages; percentages do not represent
elapsed-time estimates. UI tests require a display, like other GPU tests.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or
                   os.environ.get("WAYLAND_DISPLAY") or
                   sys.platform in ("win32", "darwin"))

try:
    from PySide6.QtCore import QCoreApplication
    from gpu_viewer.main import LoadWorker
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
        app = QCoreApplication.instance() or QCoreApplication([])
        del app  # Keep the object active through the Qt binding.
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

    def test_worker_failure_reports_error_not_readiness(self):
        app = QCoreApplication.instance() or QCoreApplication([])
        del app
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
