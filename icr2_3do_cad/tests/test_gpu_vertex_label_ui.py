"""Qt smoke tests for the viewport-wide pointer-name overlay toggle."""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from n3_compile import compile_n3_text
from gpu_viewer.vertex_label_data import project_vertex_labels


HAS_DISPLAY = bool(os.environ.get("DISPLAY") or
                   os.environ.get("WAYLAND_DISPLAY") or
                   sys.platform in ("win32", "darwin"))

SOURCE = """3D VERSION 3.0;
front_left: [<0,0,0>];
rear_right: [<100,0,0>];
top: [<0,100,0>];
face: POLY <42> {front_left,rear_right,top};
root: LIST {face};
"""


@unittest.skipUnless(HAS_DISPLAY, "Requires a Qt desktop or Xvfb")
class GPUVertexLabelUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtCore import Qt
            from PySide6.QtWidgets import QApplication
            from gpu_viewer.main import Window
        except (ImportError, SystemExit) as error:
            raise unittest.SkipTest(str(error))
        cls.Qt = Qt
        cls.app = QApplication.instance() or QApplication([])
        cls.window = Window()
        cls.model, _ = compile_n3_text(
            SOURCE, Path("labels.3d"), associate_planes=False)

    @classmethod
    def tearDownClass(cls):
        cls.window.source_pane.reset()
        cls.window.close()

    def setUp(self):
        self.window.vertex_labels_toggle.setChecked(False)
        self.window.vertex_label_mode_combo.setCurrentIndex(0)

    def test_toggle_above_viewport_is_off_by_default_and_mouse_transparent(self):
        window = self.window
        overlay = window.viewer.vertex_label_overlay
        self.assertIs(window.vertex_labels_toggle.parentWidget(),
                      window.distance_bar)
        self.assertIs(overlay.parentWidget(), window.viewer)
        self.assertEqual(overlay.objectName(), "allVertexLabelsOverlay")
        self.assertFalse(window.vertex_labels_toggle.isChecked())
        self.assertEqual(window.vertex_label_mode_combo.currentData(), "all")
        self.assertTrue(overlay.isHidden())
        self.assertTrue(overlay.testAttribute(
            self.Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        window.vertex_labels_toggle.setChecked(True)
        self.assertFalse(overlay.isHidden())
        self.assertTrue(window.viewer.pick_mode in ("vertex", "polygon"))
        window.vertex_labels_toggle.setChecked(False)
        self.assertTrue(overlay.isHidden())

    def test_modes_are_independently_selectable_without_rewriting_geometry(self):
        window = self.window
        combo = window.vertex_label_mode_combo
        self.assertIs(combo.parentWidget(), window.distance_bar)
        self.assertEqual(combo.count(), 3)
        self.assertEqual([combo.itemData(i) for i in range(combo.count())],
                         ["all", "visible", "selected"])
        window.vertex_labels_toggle.setChecked(True)
        for mode in ("selected", "visible", "all"):
            combo.setCurrentIndex(combo.findData(mode))
            self.assertEqual(window.viewer.vertex_label_mode, mode)
            self.assertFalse(window.viewer.vertex_label_overlay.isHidden())
        window.vertex_labels_toggle.setChecked(False)
        self.assertTrue(window.viewer.vertex_label_overlay.isHidden())
        self.assertEqual(window.viewer.vertex_label_mode, "all")
        self.assertFalse(window.source_pane.dirty)

    def test_selected_polygon_mode_follows_source_polygon_selection(self):
        view = self.window.viewer
        combo = self.window.vertex_label_mode_combo
        view._model = self.model
        poly = self.model.n3_label_offsets["face"]
        combo.setCurrentIndex(combo.findData("selected"))
        view.set_source_inspection("polygon", poly)
        self.assertEqual(view.inspection_kind, "polygon")
        self.assertEqual(view.inspection_offset, poly)
        # The source target shares exactly the selected polygon's pointers.
        from gpu_viewer.vertex_label_data import polygon_vertex_refs
        self.assertEqual(polygon_vertex_refs(self.model, (poly,)), {
            self.model.n3_label_offsets[label]
            for label in ("front_left", "rear_right", "top")
        })
        view.set_source_inspection()
        self.assertIsNone(view.inspection_offset)

    def test_selection_uses_yellow_not_other_vertex_blue(self):
        view = self.window.viewer
        view._vertex_picker = SimpleNamespace(
            offsets=np.array([11, 12], dtype=np.int64),
            normalized=np.array([[0, 0, 0], [0.2, 0, 0]], dtype=np.float64))
        view._label_vertex_picker = view._vertex_picker
        view.vertex_pointer_names = {11: "front_left", 12: "rear_right"}
        view.set_source_inspection("vertex", 11)
        self.window.vertex_labels_toggle.setChecked(True)
        entries = project_vertex_labels(
            view._vertex_picker, view.vertex_pointer_names,
            np.eye(4), 640, 480)
        self.assertEqual([item[3] for item in entries],
                         ["front_left", "rear_right"])
        self.assertEqual(view.inspection_offset, 11)
        self.assertNotEqual(view.colors["viewport_all_vertex_dot"],
                            view.colors["viewport_vertex_dot"])
        # Overlay is display-only. No geometry/source modification occurs.
        self.assertFalse(self.window.source_pane.dirty)

    def test_color_customization_reaches_overlay(self):
        view = self.window.viewer
        colors = dict(view.colors)
        colors["viewport_all_vertex_dot"] = "#1199CC"
        colors["viewport_all_vertex_label"] = "#EECCFF"
        view.set_appearance_colors(colors)
        self.assertEqual(view.colors["viewport_all_vertex_dot"], "#1199CC")
        self.assertEqual(view.colors["viewport_all_vertex_label"], "#EECCFF")
        self.assertNotEqual(view.colors["viewport_vertex_dot"], "#1199CC")


if __name__ == "__main__":
    unittest.main()
