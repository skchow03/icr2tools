import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:  # pragma: no cover - import guard for environments without Qt
    from PyQt5 import QtWidgets  # noqa: E402
    from icr2timing.ui.control_panel import ControlPanel  # noqa: E402
except ImportError:  # pragma: no cover - import guard for environments without Qt
    QtWidgets = None
    ControlPanel = None

from icr2timing.core.config import Config  # noqa: E402


class DummyMemory:
    def __init__(self, detected_version: str):
        self.detected_version = detected_version
        self.writes = []

    def write(self, offset, type_name, value):
        self.writes.append((offset, type_name, value))


@unittest.skipIf(ControlPanel is None, "PyQt5 not available")
class ControlPanelHelperVersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_helpers_blocked_when_version_mismatch(self):
        cfg = Config()
        cfg.version = "REND32A"
        mem = DummyMemory("DOS")

        panel = ControlPanel(updater=None, mem=None, cfg=cfg)
        try:
            panel.attach_runtime(None, mem, cfg)
            panel._latest_state = SimpleNamespace(car_states={})

            panel._release_all_cars()
            panel._force_all_cars_to_pit()

            self.assertFalse(mem.writes)
            self.assertFalse(panel.btnReleaseAllCars.isEnabled())
            self.assertFalse(panel.btnForcePitStops.isEnabled())

            message = panel.statusbar.currentMessage()
            self.assertIn("unavailable", message)
            self.assertIn("DOS", message)
            self.assertIn("REND32A", message)
        finally:
            panel.close()
            panel.deleteLater()


if __name__ == "__main__":
    unittest.main()
