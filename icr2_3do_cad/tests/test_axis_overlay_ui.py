"""Qt compositing and viewport controls for the CAD XYZ orientation guides."""
import os
import sys
import unittest
from types import SimpleNamespace

import numpy as np

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or
                   os.environ.get("WAYLAND_DISPLAY") or
                   sys.platform in ("win32", "darwin"))


@unittest.skipUnless(HAS_DISPLAY, "Requires Qt desktop or Xvfb")
class AxisOverlayUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication, QWidget
            from PySide6.QtCore import Qt, QSettings
            from PySide6.QtGui import QImage
            from icr2_3do_cad import Window
            from axis_overlay import AxisGuideOverlay
        except (ImportError, SystemExit) as exc:
            raise unittest.SkipTest(str(exc))
        cls.app = QApplication.instance() or QApplication([])
        cls.Qt = Qt
        cls.QImage = QImage
        cls.Window = Window
        cls.AxisGuideOverlay = AxisGuideOverlay
        cls.settings = QSettings("ICR2Tools", "3DOCAD")
        cls.original = {
            name: cls.settings.value(name)
            for name in ("axis_guides_enabled", "orientation_gizmo_enabled",
                         "axis_guide_anchor")
        }

    @classmethod
    def tearDownClass(cls):
        for key, val in cls.original.items():
            if val is None:
                cls.settings.remove(key)
            else:
                cls.settings.setValue(key, val)
        cls.settings.sync()

    def test_display_settings_menu_and_transparent_layer(self):
        w = self.Window()
        try:
            v = w.viewer
            layer = v.axis_guide_overlay
            self.assertEqual(layer.objectName(), "cadAxisGuideOverlay")
            self.assertTrue(layer.testAttribute(
                self.Qt.WidgetAttribute.WA_TransparentForMouseEvents))
            self.assertTrue(layer.testAttribute(
                self.Qt.WidgetAttribute.WA_TranslucentBackground))
            self.assertEqual(v.axis_guide_anchor, "focus")
            self.assertEqual(w.axis_anchor_combo.currentData(), "focus")
            self.assertTrue(w.axis_guides_toggle.isChecked())
            self.assertTrue(w.orientation_gizmo_toggle.isChecked())
            self.assertFalse(layer.isHidden())
            w.axis_guides_toggle.setChecked(False)
            self.assertFalse(v.axis_guides_enabled)
            self.assertFalse(layer.isHidden())
            w.orientation_gizmo_toggle.setChecked(False)
            self.assertFalse(v.orientation_gizmo_enabled)
            self.assertTrue(layer.isHidden())
            w.axis_guides_toggle.setChecked(True)
            self.assertFalse(layer.isHidden())
            w.axis_anchor_combo.setCurrentIndex(
                w.axis_anchor_combo.findData("origin"))
            self.assertEqual(v.axis_guide_anchor, "origin")
            self.assertEqual(self.settings.value("axis_guide_anchor"),
                             "origin")
            # Display Options checkboxes remain synchronized with settings.
            options = [a for a in w.menuBar().actions()
                       if a.menu() and "View" in a.text()]
            self.assertTrue(options)
            menu = options[0].menu()
            display = [a.menu() for a in menu.actions()
                       if a.menu() and "Display" in a.text()]
            self.assertTrue(display)
            actions = [a for a in display[0].actions() if a.isCheckable()]
            self.assertTrue(any("axis" in a.text().lower() for a in actions))
            self.assertTrue(any("orientation" in a.text().lower()
                                for a in actions))
        finally:
            w.close()
            self.app.processEvents()

    def test_axes_render_in_separate_mouse_transparent_widget(self):
        from PySide6.QtWidgets import QWidget
        from PySide6.QtGui import QImage
        from PySide6.QtCore import Qt

        class StubViewport(QWidget):
            def __init__(self):
                super().__init__()
                self.axis_guides_enabled = True
                self.orientation_gizmo_enabled = True
                self.axis_guide_anchor = "focus"
                self.distance = 4.
                self.half_height = 1.6
                self._mesh = SimpleNamespace(
                    center=np.zeros(3), scale=1.)
                self.view = np.eye(4)
                self.view[2, 3] = -4.
            def _projection_and_view(self):
                p = np.diag((.5, .5, -.02, 1.))
                return p, self.view

        root = StubViewport()
        root.resize(640, 480)
        overlay = self.AxisGuideOverlay(root)
        overlay.setGeometry(root.rect())
        root.show()
        overlay.show()
        self.app.processEvents()
        try:
            image = overlay.grab().toImage().convertToFormat(
                QImage.Format.Format_RGBA8888)
            self.assertFalse(image.isNull())
            # Not a purely transparent overlay: both corner legend and
            # cross-screen model axes are rasterized by Qt.
            pixels = np.frombuffer(
                image.bits(), dtype=np.uint8, count=image.sizeInBytes())
            rgba = pixels.reshape(image.height(), image.bytesPerLine())[
                :, :image.width()*4].reshape(image.height(), image.width(), 4)
            self.assertGreater(np.count_nonzero(rgba[..., 3]), 100)
            self.assertGreater(np.count_nonzero(
                rgba[230:250, 280:360, 3]), 12)
            self.assertGreater(np.count_nonzero(
                rgba[330:465, 0:145, 3]), 100)
            # Pan/orbit changes the triad, not the global XYZ assignment.
            before = image.copy()
            overlay.viewport.view = np.array(
                ((0., 1., 0., 0.), (0., 0., 1., 0.),
                 (1., 0., 0., -4.), (0., 0., 0., 1.)))
            overlay.update()
            self.app.processEvents()
            after = overlay.grab().toImage().convertToFormat(
                QImage.Format.Format_RGBA8888)
            self.assertNotEqual(before, after)
        finally:
            root.close()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
