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

    def test_horiz_eye_controls_only_change_background_position(self):
        from gpu_viewer.skybox import SKY_EYE
        view = self.window.viewer
        self.assertEqual(view.sky_eye, tuple(SKY_EYE))
        before = view._camera_eye_model()
        # Without a loaded HORIZ the controls are disabled to users,
        # but programmatic changes still exercise the signal/renderer wiring.
        for spin in self.window.sky_eye_spins:
            self.assertFalse(spin.isEnabled())
        self.window.sky_eye_spins[0].setValue(150)
        self.window.sky_eye_spins[1].setValue(-250)
        self.window.sky_eye_spins[2].setValue(900)
        self.assertEqual(view.sky_eye, (150., -250., 900.))
        self.assertEqual(view._camera_eye_model(), before)
        self.window.sky_eye_reset_button.setEnabled(True)
        self.window.sky_eye_reset_button.click()
        self.assertEqual(view.sky_eye, tuple(SKY_EYE))
        self.window.sky_eye_reset_button.setEnabled(False)
    def test_onboard_bank_roll_rotates_view_and_horiz_but_not_eye(self):
        import numpy as np
        from types import SimpleNamespace
        from gpu_viewer.main import camera_view
        from gpu_viewer.skybox import skybox_view_matrix
        view = self.window.viewer
        self.nav.trk.xsect_data = [
            [0, 0, 0, 24000, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0],
        ] * 2
        view._update_track_drive_pose()
        pose = view._track_drive_pose
        self.assertLess(pose.roll, 0)
        eye = view._camera_eye_model()
        rolled, _, _ = view._camera_view_matrix()
        unrolled, _, _ = camera_view(
            view.azimuth, view.elevation, view.distance, view.target)
        np.testing.assert_allclose(rolled[2], unrolled[2])
        self.assertFalse(np.allclose(rolled[:2, :3], unrolled[:2, :3]))
        self.assertEqual(view._camera_eye_model(), eye)
        fake_sky_mesh = SimpleNamespace(center=(0., 0., 0.), scale=1.)
        sky_rolled = skybox_view_matrix(rolled, fake_sky_mesh)
        sky_unrolled = skybox_view_matrix(unrolled, fake_sky_mesh)
        self.assertFalse(np.allclose(sky_rolled[:3, :3],
                                      sky_unrolled[:3, :3]))
        self.assertIn('bank', self.window.trk_drive_status.text())
        view.set_track_drive_enabled(False)
        restored, _, _ = view._camera_view_matrix()
        expected, _, _ = camera_view(
            view.azimuth, view.elevation, view.distance, view.target)
        np.testing.assert_allclose(restored, expected)

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
