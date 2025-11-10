import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

try:  # pragma: no cover - import guard for environments without Qt
    from PyQt5 import QtWidgets  # noqa: E402
    from icr2timing.overlays.individual_car_overlay import (  # noqa: E402
        IndividualCarOverlay,
    )
    from icr2timing.core.config import Config  # noqa: E402
except ImportError:  # pragma: no cover - import guard for environments without Qt
    QtWidgets = None
    IndividualCarOverlay = None
    Config = None


@unittest.skipIf(IndividualCarOverlay is None, "PyQt5 not available")
class IndividualCarOverlayFreezeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):  # pragma: no cover - GUI bootstrap
        cls._app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_freeze_skips_writes_on_version_mismatch(self):
        mem = MagicMock()
        mem.detected_version = "DOS"
        cfg = Config()
        cfg.version = "REND32A"

        overlay = IndividualCarOverlay(mem=mem, cfg=cfg)
        overlay.set_backend(mem, cfg, version="DOS")

        overlay._locked_values.set(overlay.car_index, 1, 123)
        overlay._latest_state = SimpleNamespace(
            car_states={
                overlay.car_index: SimpleNamespace(values=[0] * overlay._values_per_car)
            }
        )

        self.assertEqual(
            overlay._freeze_warning_message,
            overlay._freeze_unavailable_message(),
        )

        # Even with locked values queued up, mismatch should prevent writes.
        overlay._freeze_checkbox.setEnabled(True)
        overlay._freeze_checkbox.setChecked(True)
        self.assertTrue(overlay._freeze_checkbox.isChecked())
        overlay._apply_locked_values()

        mem.write.assert_not_called()


if __name__ == "__main__":  # pragma: no cover - manual test hook
    unittest.main()
