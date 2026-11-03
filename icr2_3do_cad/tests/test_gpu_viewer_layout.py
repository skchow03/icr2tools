"""Small UI smoke tests for the GPU viewer's simplified inspector layout.

Requires a Qt-capable desktop (or xvfb-run) and the gpu_viewer requirements.
No OpenGL model is loaded, so these tests do not exercise rendering.
"""
import os
import sys
import unittest


HAS_DISPLAY = bool(os.environ.get("DISPLAY") or
                   os.environ.get("WAYLAND_DISPLAY") or
                   sys.platform in ("win32", "darwin"))


@unittest.skipUnless(HAS_DISPLAY, "Requires a desktop or xvfb-run")
class GPUViewerLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            from gpu_viewer.main import Window
        except (ImportError, SystemExit) as error:
            raise unittest.SkipTest(f"GPU viewer requirements unavailable: {error}")
        cls.app = QApplication.instance() or QApplication([])
        cls.window = Window()

    @classmethod
    def tearDownClass(cls):
        cls.window.close()

    def test_sidebar_is_collapsible_and_viewport_is_primary(self):
        from PySide6.QtWidgets import QToolButton
        headers = {h.text(): h for h in
                   self.window.sidebar_content.findChildren(QToolButton)}
        self.assertEqual(self.window.main_splitter.count(), 2)
        self.assertEqual(self.window.editor_splitter.count(), 2)
        self.assertTrue(headers["Model"].isChecked())
        self.assertTrue(headers["Display"].isChecked())
        self.assertFalse(headers["Assets"].isChecked())
        self.assertFalse(headers["Advanced diagnostics"].isChecked())
        headers["Assets"].setChecked(True)
        self.assertTrue(headers["Assets"].isChecked())
        headers["Assets"].setChecked(False)

    def test_single_lod_choice_preserves_modes(self):
        selector = self.window.lod_mode_combo
        self.assertEqual(selector.currentData(), "auto")
        self.assertEqual(self.window.viewer.lod_distance, "auto")
        self.assertFalse(self.window.lod_spin.isEnabled())
        selector.setCurrentIndex(selector.findData("manual"))
        self.assertTrue(self.window.lod_spin.isEnabled())
        self.window.lod_spin.setValue(50000)
        self.assertEqual(self.window.viewer.lod_distance, 50000)
        selector.setCurrentIndex(selector.findData("all"))
        self.assertIsNone(self.window.viewer.lod_distance)
        self.assertFalse(self.window.lod_spin.isEnabled())
        selector.setCurrentIndex(selector.findData("auto"))
        self.assertEqual(self.window.viewer.lod_distance, "auto")

    def test_workspace_tabs_preserved_and_common_assets_not_duplicated(self):
        tabs = self.window.workspace_tabs
        self.assertEqual([tabs.tabText(i) for i in range(tabs.count())],
                         ["Car", "Track", "Object"])
        tabs.setCurrentIndex(0)
        self.assertTrue(self.window.fallback_controls.isHidden())
        tabs.setCurrentIndex(1)
        self.assertFalse(self.window.fallback_controls.isHidden())
        tabs.setCurrentIndex(2)
        self.assertFalse(self.window.fallback_controls.isHidden())


if __name__ == "__main__":
    unittest.main()
