"""Qt-keyboard tests for same-folder TRK camera controls (no OpenGL model)."""
import os
import sys
import unittest

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or
                   os.environ.get("WAYLAND_DISPLAY") or
                   sys.platform in ("win32", "darwin"))


@unittest.skipUnless(HAS_DISPLAY, "Requires Qt desktop or Xvfb")
class TrackNavigationUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtGui import QSurfaceFormat
            from PySide6.QtWidgets import QApplication
            from gpu_viewer.main import Window
        except (ImportError, SystemExit) as exc:
            raise unittest.SkipTest(str(exc))
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        fmt.setDepthBufferSize(24)
        QSurfaceFormat.setDefaultFormat(fmt)
        cls.app = QApplication.instance() or QApplication([])
        cls.window = Window()
        cls.window.show()
        cls.app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.window.close()

    def setUp(self):
        # Synthetic geometry/terrain is declared in our CPU regression suite.
        from test_gpu_track_navigation import flat_trk
        from gpu_viewer.track_navigation import TrackNavigation
        self.nav = TrackNavigation("synthetic.trk", flat_trk())
        self.window.viewer.set_track_navigation(self.nav)
        self.window.track_drive_checkbox.setEnabled(True)
        self.window.trk_reset_button.setEnabled(True)
        self.app.processEvents()
        self.window.viewer.setFocus()

    def tearDown(self):
        self.window.viewer.set_track_navigation(None)
        self.window.track_drive_checkbox.setEnabled(False)
        self.window.trk_reset_button.setEnabled(False)
        self.app.processEvents()

    def test_default_drive_and_wasd_arrow_signs(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        view = self.window.viewer
        self.assertTrue(view.track_drive_enabled)
        self.assertTrue(view.perspective)
        self.assertTrue(self.window.track_drive_checkbox.isChecked())
        self.assertFalse(self.window.perspective_toggle.isEnabled())
        self.assertEqual(view._camera_eye_model(), self.nav.pose().eye)
        QTest.keyClick(view, Qt.Key.Key_W)
        self.assertEqual(self.nav.dlong, 60000)
        QTest.keyClick(view, Qt.Key.Key_A)
        self.assertEqual(self.nav.dlat, 12000)
        QTest.keyClick(view, Qt.Key.Key_D)
        self.assertEqual(self.nav.dlat, 0)
        QTest.keyClick(view, Qt.Key.Key_S)
        self.assertEqual(self.nav.dlong, 0)
        QTest.keyClick(view, Qt.Key.Key_Right)
        self.assertEqual(self.nav.dlat, -12000)
        QTest.keyClick(view, Qt.Key.Key_Left)
        self.assertEqual(self.nav.dlat, 0)
        QTest.keyClick(view, Qt.Key.Key_Up, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(self.nav.dlong, 300000)
        QTest.keyClick(view, Qt.Key.Key_Down)
        self.assertEqual(self.nav.dlong, 240000)
        self.assertIn("DLONG", self.window.trk_drive_status.text())
        self.assertIn("DLAT", self.window.trk_drive_status.text())

    def test_steps_reset_and_disable_restore_free_camera(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        view = self.window.viewer
        self.window.trk_forward_step.setValue(15)
        self.window.trk_lateral_step.setValue(3)
        QTest.keyClick(view, Qt.Key.Key_W)
        QTest.keyClick(view, Qt.Key.Key_A)
        self.assertEqual(self.nav.dlong, 90000)
        self.assertEqual(self.nav.dlat, 18000)
        self.window.trk_reset_button.click()
        self.assertEqual(self.nav.dlong, 0)
        self.assertEqual(self.nav.dlat, 0)
        self.window.track_drive_checkbox.setChecked(False)
        self.assertFalse(view.track_drive_enabled)
        self.assertTrue(self.window.perspective_toggle.isEnabled())
        # Other camera modes still work and can be restored via checkbox.
        self.window.track_drive_checkbox.setChecked(True)
        self.assertTrue(view.track_drive_enabled)
        view.frame_all()
        self.assertFalse(view.track_drive_enabled)
        self.assertFalse(self.window.track_drive_checkbox.isChecked())
        self.window.trk_forward_step.setValue(10)
        self.window.trk_lateral_step.setValue(2)


if __name__ == "__main__":
    unittest.main()
