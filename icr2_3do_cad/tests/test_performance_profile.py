"""Opt-in profiler regression tests: no Tk display or model assets required."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from performance_profile import PerformanceRecorder, profiled


class PerformanceTests(unittest.TestCase):
    def test_disabled_recorder_collects_nothing(self):
        rec=PerformanceRecorder(False)
        with rec.measure("load.compile_n3"):
            pass
        rec.record("viewport.redraw",1.0)
        self.assertEqual(rec.snapshot(),{})

    def test_measurement_and_statistics(self):
        rec=PerformanceRecorder(True)
        rec.record("viewport.redraw",.010)
        rec.record("viewport.redraw",.030)
        with rec.measure("load.compile_n3"):
            time.sleep(.001)
        stats=rec.snapshot()
        self.assertEqual(stats["viewport.redraw"]["count"],2)
        self.assertAlmostEqual(stats["viewport.redraw"]["mean_ms"],20)
        self.assertEqual(stats["viewport.redraw"]["max_ms"],30)
        self.assertGreater(stats["load.compile_n3"]["total_ms"],0)

    def test_decorator_preserves_return_and_exceptions(self):
        rec=PerformanceRecorder(True)
        @profiled(rec,"ui.refresh")
        def f(x):
            return x+2
        self.assertEqual(f(5),7)
        self.assertEqual(rec.snapshot()["ui.refresh"]["count"],1)

    def test_report_is_machine_readable(self):
        rec=PerformanceRecorder(True)
        rec.record("viewport.redraw",.05)
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/"report.json"
            rec.write(target)
            report=json.loads(target.read_text())
            self.assertEqual(report["schema"],1)
            self.assertEqual(report["units"],"milliseconds")
            self.assertEqual(report["stages"]["viewport.redraw"]["count"],1)
            self.assertNotIn("filename",report)


if __name__=="__main__":
    unittest.main()
