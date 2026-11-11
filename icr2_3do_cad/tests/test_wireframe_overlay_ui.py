"""Regression tests for independent polygon edges and vertex markers."""
import os
import sys
import unittest

import numpy as np

DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
               or sys.platform in ("win32", "darwin"))

SOURCE = """3D VERSION 3.0;
back_a: [<-30000,-30000,0>];
back_b: [<30000,-30000,0>];
back_c: [<30000,30000,0>];
back_d: [<-30000,30000,0>];
front_a: [<-100000,-100000,50000>];
front_b: [<100000,-100000,50000>];
front_c: [<100000,100000,50000>];
front_d: [<-100000,100000,50000>];
back_face: POLY <42> {back_a,back_b,back_c,back_d};
front_face: POLY <43> {front_a,front_b,front_c,front_d};
root: LIST {back_face,front_face};
"""


@unittest.skipUnless(DISPLAY, "Requires desktop or Xvfb")
class CADWireframeOverlayUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            from icr2_3do_cad import Window
        except (ImportError, SystemExit) as error:
            raise unittest.SkipTest(str(error))
        cls.app = QApplication.instance() or QApplication([])
        cls.window = Window()

    @classmethod
    def tearDownClass(cls):
        cls.window.source_pane.reset()
        cls.window.close()

    def setUp(self):
        self.window.wireframe_toggle.setChecked(False)
        self.window.wireframe_visible_toggle.setChecked(True)
        self.window.vertex_labels_toggle.setChecked(False)
        self.window.vertex_names_toggle.setChecked(True)
        self.window.vertex_label_mode_combo.setCurrentIndex(0)

    def test_toolbar_toggles_are_independent_of_render_mode_and_editing(self):
        window = self.window
        view = window.viewer
        for widget in (window.wireframe_toggle,
                       window.wireframe_visible_toggle,
                       window.vertex_labels_toggle,
                       window.vertex_label_mode_combo,
                       window.vertex_names_toggle):
            self.assertIs(widget.parentWidget(), window.distance_bar)
        self.assertFalse(window.wireframe_toggle.isChecked())
        self.assertTrue(window.wireframe_visible_toggle.isChecked())
        self.assertFalse(window.vertex_labels_toggle.isChecked())
        self.assertEqual(view.render_mode, "painter")
        window.wireframe_toggle.setChecked(True)
        self.assertTrue(view.wireframe_overlay_enabled)
        window.wireframe_visible_toggle.setChecked(False)
        self.assertFalse(view.wireframe_visible_only)
        window.vertex_labels_toggle.setChecked(True)
        self.assertFalse(view.vertex_label_overlay.isHidden())
        window.vertex_label_mode_combo.setCurrentIndex(
            window.vertex_label_mode_combo.findData("visible"))
        self.assertEqual(view.vertex_label_mode, "visible")
        window.vertex_names_toggle.setChecked(False)
        self.assertFalse(view.vertex_names_enabled)
        self.assertEqual(view.render_mode, "painter")
        self.assertFalse(window.source_pane.dirty)

    def test_view_menu_controls_sync_with_toolbar(self):
        window = self.window
        view_menu = next(
            action.menu() for action in window.menuBar().actions()
            if action.text().replace("&", "") == "View")
        options = next(
            action.menu() for action in view_menu.actions()
            if action.text().replace("&", "") == "Display Options")
        actions = {action.text().replace("&", ""): action
                   for action in options.actions()}
        self.assertEqual(actions["Polygon edges"].shortcut().toString(),
                         "Ctrl+Shift+W")
        actions["Polygon edges"].trigger()
        self.assertTrue(window.wireframe_toggle.isChecked())
        self.assertTrue(actions["Polygon edges"].isChecked())
        actions["Front edges only"].trigger()
        self.assertFalse(window.wireframe_visible_toggle.isChecked())
        actions["Vertices"].trigger()
        self.assertTrue(window.vertex_labels_toggle.isChecked())
        actions["Vertex names"].trigger()
        self.assertFalse(window.vertex_names_toggle.isChecked())


@unittest.skipUnless(DISPLAY, "Requires desktop or Xvfb GL")
class CADWireframeOverlayGLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtGui import QSurfaceFormat
            from PySide6.QtWidgets import QApplication
            from icr2_3do_cad import GLViewport
        except (ImportError, SystemExit) as error:
            raise unittest.SkipTest(str(error))
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        fmt.setDepthBufferSize(24)
        QSurfaceFormat.setDefaultFormat(fmt)
        cls.app = QApplication.instance() or QApplication([])
        cls.GLViewport = GLViewport

    def setUp(self):
        from n3_compile import compile_n3_text
        from mesh import make_mesh
        from scene import build_scene
        from textures import build_atlas
        self.model, _ = compile_n3_text(
            SOURCE, "overlay.3d", associate_planes=False)
        self.original_raw = self.model.raw
        scene = build_scene(self.model)
        palette = np.zeros((256, 3), dtype=np.uint8)
        palette[42] = (90, 130, 170)
        palette[43] = (160, 130, 90)
        atlas = build_atlas(scene.geometry, "overlay.3d")
        mesh = make_mesh(scene.geometry, palette.astype(np.float32)/255, atlas)
        self.view = self.GLViewport()
        self.view.resize(640, 480)
        self.view.show()
        self.app.processEvents()
        self.assertTrue(self.view.context().isValid())
        self.view.set_mesh(mesh, self.model, atlas, palette, scene)
        self.view.set_view("Top")
        self.view.half_height = 1.5
        self.view.set_render_mode("depth")

    def tearDown(self):
        self.view.shutdown_gl()
        self.view.close()
        self.app.processEvents()

    def _pixels(self):
        from PySide6.QtGui import QImage
        self.view.update()
        self.view.repaint()
        bitmap = self.view.grabFramebuffer().convertToFormat(
            QImage.Format.Format_RGBA8888)
        return np.frombuffer(
            bitmap.bits(), dtype=np.uint8,
            count=bitmap.sizeInBytes()).copy().reshape(-1, 4)

    def test_front_only_occludes_hidden_edges_without_changing_model(self):
        base = self._pixels()
        self.view.set_wireframe_overlay_enabled(True)
        self.view.set_wireframe_visible_only(True)
        visible = self._pixels()
        self.assertEqual(self.view._wire_visibility_mode, "overlay")
        self.assertIsNotNone(self.view._wire_mesh)
        self.assertGreater(self.view._wire_index_count, 0)
        self.view.set_wireframe_visible_only(False)
        xray = self._pixels()
        shown = np.count_nonzero(np.any(visible[:, :3] != base[:, :3], axis=1))
        through = np.count_nonzero(np.any(xray[:, :3] != base[:, :3], axis=1))
        self.assertGreater(shown, 0, "No polygon edges rendered")
        self.assertGreater(through, shown,
                           "Hidden rear-square edges should appear in X-ray")
        self.view.set_wireframe_overlay_enabled(False)
        self.assertTrue(np.array_equal(base, self._pixels()))
        self.assertEqual(self.model.raw, self.original_raw)
        self.assertEqual(self.view.render_mode, "depth")


if __name__ == "__main__":
    unittest.main()
