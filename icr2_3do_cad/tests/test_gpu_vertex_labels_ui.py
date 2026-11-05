"""Qt and OpenGL widget integration: show all purple vertex dots/names."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from gpu_viewer.appearance import DARK_COLORS
from gpu_viewer.mesh import make_mesh
from gpu_viewer.scene import build_scene
from gpu_viewer.textures import build_atlas
from n3_compile import compile_n3_text

DISPLAY = bool(os.environ.get("DISPLAY") or
               os.environ.get("WAYLAND_DISPLAY") or
               sys.platform in ("win32", "darwin"))

SOURCE = """3D VERSION 3.0;
corner1: [<-100000,-100000,0>];
corner2: [<100000,-100000,0>];
corner3: [<100000,100000,0>];
corner4: [<-100000,100000,0>];
plane_only: [<0,0,50000>];
panel: POLY <44> {corner1,corner2,corner3,corner4};
root: BSPF (corner1,corner2,plane_only), NIL,panel,NIL;
"""


@unittest.skipUnless(DISPLAY, "Requires Qt desktop or Xvfb")
class VertexLabelsUIIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtGui import QSurfaceFormat
            from PySide6.QtWidgets import QApplication
            from gpu_viewer.main import Window
            import gpu_viewer.main as main
        except (ImportError, SystemExit) as exc:
            raise unittest.SkipTest(str(exc))
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        fmt.setDepthBufferSize(24)
        QSurfaceFormat.setDefaultFormat(fmt)
        cls.app = QApplication.instance() or QApplication([])
        cls.Window = Window
        cls.main = main

    def setUp(self):
        from PySide6.QtCore import QSettings
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        settings_file = str(Path(self.temp.name) / "vertex_labels.ini")
        self.patch_settings = patch.object(
            self.main, "QSettings",
            side_effect=lambda *args: QSettings(
                settings_file, QSettings.Format.IniFormat))
        self.patch_settings.start()
        self.addCleanup(self.patch_settings.stop)
        self.settings_file = settings_file

        self.window = self.Window()
        self.window.resize(1300, 870)
        self.window.show()
        self.app.processEvents()
        self.model, _ = compile_n3_text(
            SOURCE, "label_ui.3d", associate_planes=False)
        scene = build_scene(self.model)
        palette = np.zeros((256, 3), dtype=np.uint8)
        palette[44] = (40, 40, 40)
        atlas = build_atlas(scene.geometry, "label_ui.3d")
        mesh = make_mesh(scene.geometry, palette.astype(np.float32)/255., atlas)
        self.window.viewer.set_mesh(
            mesh, self.model, atlas, palette, scene)
        self.window.viewer.set_view("Top")
        self.window.viewer.half_height = 0.85
        self.app.processEvents()

    def tearDown(self):
        self.window.source_pane.reset()
        self.window.viewer.shutdown_gl()
        self.window.close()
        self.app.processEvents()

    def _repaint_overlay(self):
        self.window.viewer.update()
        self.window.viewer.repaint()
        self.window.viewer.vertex_labels_overlay.repaint()
        self.app.processEvents()
        return self.window.viewer.vertex_labels_overlay

    def test_above_viewport_toggle_controls_overlay_and_keeps_mouse_picking(self):
        from PySide6.QtCore import Qt
        checkbox = self.window.vertex_labels_toggle
        overlay = self.window.viewer.vertex_labels_overlay
        self.assertEqual(checkbox.objectName(), "viewportVertexLabelsToggle")
        self.assertFalse(checkbox.isChecked())
        self.assertFalse(overlay.isVisible())
        self.assertEqual(self.window.distance_bar.parent(), self.window.viewport_panel)
        checkbox.click()
        self.assertTrue(checkbox.isChecked())
        self.assertTrue(overlay.isVisible())
        self.assertTrue(overlay.testAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        self.assertEqual(overlay.size(), self.window.viewer.size())
        visible = self._repaint_overlay().last_visible_labels
        self.assertEqual(
            {point.label for point in visible},
            {"corner1", "corner2", "corner3", "corner4"})
        checkbox.click()
        self.assertFalse(overlay.isVisible())
        self.assertEqual(overlay.last_visible_labels, ())

    def test_source_only_plane_vertex_label_and_selected_dot_color_priority(self):
        self.window.vertex_labels_toggle.setChecked(True)
        viewer = self.window.viewer
        labels = self.window.source_pane
        labels.set_source(SOURCE, Path("label_ui.3d"))
        viewer.set_source_vertex_labels(labels._source_index.vertex_labels)
        overlay = self._repaint_overlay()
        self.assertIn("plane_only",
                      {point.label for point in overlay.last_visible_labels})
        self.assertNotEqual(
            viewer.colors["viewport_all_vertex_dot"],
            viewer.colors["viewport_vertex_dot"])
        self.assertNotEqual(
            viewer.colors["viewport_all_vertex_dot"],
            viewer.colors["viewport_bsp_vertex"])
        selected = self.model.n3_label_offsets["corner1"]
        viewer.set_source_inspection("vertex", selected)
        self._repaint_overlay()
        self.assertEqual(viewer.inspection_kind, "vertex")
        self.assertIn("corner1",
                      {point.label for point in overlay.last_visible_labels})
        self.assertEqual(
            viewer.inspection_offset, selected)
        original_model_bytes = self.model.raw
        viewer.set_appearance_colors(dict(
            DARK_COLORS, viewport_all_vertex_dot="#FC32BD",
            viewport_all_vertex_text="#EE44AA"))
        self._repaint_overlay()
        self.assertEqual(viewer.colors["viewport_all_vertex_dot"], "#FC32BD")
        self.assertEqual(self.model.raw, original_model_bytes)

    def test_toggling_persists_in_settings_and_menu_is_synchronized(self):
        from PySide6.QtCore import QSettings
        action = next(a.menu() for a in self.window.menuBar().actions()
                      if a.text().replace("&", "") == "View")
        options = next(a.menu() for a in action.actions()
                       if "Display Options" in a.text().replace("&", ""))
        menu_action = next(a for a in options.actions()
                           if "Vertex dots" in a.text())
        self.assertFalse(menu_action.isChecked())
        menu_action.trigger()
        self.assertTrue(self.window.vertex_labels_toggle.isChecked())
        self.assertTrue(menu_action.isChecked())
        config = QSettings(self.settings_file, QSettings.Format.IniFormat)
        self.assertIn(str(config.value("viewport/show_vertex_labels")).lower(),
                      {"true", "1"})
        menu_action.trigger()
        self.assertFalse(self.window.vertex_labels_toggle.isChecked())
        self.assertIn(str(config.value("viewport/show_vertex_labels")).lower(),
                      {"false", "0"})
        self.window.vertex_labels_toggle.setChecked(True)
        # Reopening a Viewer with the same QSettings recovers the choice.
        other = self.Window()
        try:
            self.assertTrue(other.vertex_labels_toggle.isChecked())
        finally:
            other.source_pane.reset()
            other.close()

    def test_composited_qt_overlay_paints_label_pixels_separately_from_gl(self):
        from PySide6.QtGui import QImage
        self.window.vertex_labels_toggle.setChecked(True)
        overlay = self._repaint_overlay()
        image = overlay.grab().toImage().convertToFormat(
            QImage.Format.Format_RGBA8888)
        pix = np.frombuffer(image.bits(), dtype=np.uint8,
                            count=image.sizeInBytes())
        pixels = pix.reshape(image.height(), image.bytesPerLine())[
            :, :image.width()*4].reshape(
                image.height(), image.width(), 4)
        r, g, b, alpha = (pixels[:, :, i].astype(np.int32) for i in range(4))
        # Purple/magenta dots and glyphs must exist in Qt's actual child
        # paint layer, not in OpenGL's framebuffer.
        purple = ((r > 130) & (b > 145) & (g > 75) & (alpha > 100))
        self.assertGreater(int(purple.sum()), 60)


if __name__ == "__main__":
    unittest.main()
