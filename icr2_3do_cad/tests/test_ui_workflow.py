"""UI workflow regressions for selection context, camera presets, and safer framing."""
import math
from pathlib import Path
import unittest

from icr2_3do_cad import Editor

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


class UIWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.app = Editor()
        self.app.withdraw()
        self.assertTrue(self.app.load_file(FIXTURES / "roadcar.3do"))

    def tearDown(self):
        self.app.destroy()

    def test_toolbar_and_collapsed_advanced_controls(self):
        app = self.app
        self.assertFalse(app.show_view_settings.get())
        self.assertFalse(app.show_header_details.get())
        self.assertFalse(app.show_advanced_polygon.get())
        self.assertFalse(app.view_options.winfo_manager())
        self.assertFalse(app.diagnostics_frame.winfo_manager())
        self.assertFalse(app.poly_advanced_container.winfo_manager())
        app.show_view_settings.set(True)
        app.toggle_view_settings()
        self.assertEqual(app.view_options.winfo_manager(), "pack")
        app.show_header_details.set(True)
        app.toggle_header_details()
        self.assertEqual(app.diagnostics_frame.winfo_manager(), "pack")
        app.show_advanced_polygon.set(True)
        app.toggle_polygon_advanced()
        self.assertEqual(app.poly_advanced_container.winfo_manager(), "pack")
        self.assertTrue(app.poly_plane_combo.winfo_exists())
        app.show_advanced_polygon.set(False)
        app.toggle_polygon_advanced()
        self.assertFalse(app.poly_advanced_container.winfo_manager())

    def test_camera_presets_are_non_destructive(self):
        app = self.app
        original = app.model.build_modified_bytes()[0]
        for preset, az, el in (
            ("Three-quarter", 35, 25),
            ("Top", 0, 89),
            ("Front", 0, 0),
            ("Side", 90, 0),
        ):
            app.set_camera_view(preset)
            self.assertAlmostEqual(app.azimuth, math.radians(az))
            self.assertAlmostEqual(app.elevation, math.radians(el))
        with self.assertRaises(ValueError):
            app.set_camera_view("Unknown")
        self.assertEqual(app.model.build_modified_bytes()[0], original)
        self.assertFalse(app.model.dirty)

    def test_polygon_selection_context_and_frame(self):
        app = self.app
        app.notebook.select(app.poly_page)
        ref = next(iter(app.model.polygons))
        poly = app.model.polygons[ref]
        app.choose_polygon(ref)
        self.assertIn(f"Polygon @{ref}", app.context_title.get())
        self.assertEqual(str(app.frame_selected_button["state"]), "normal")
        points = [app.model.vertices[v].xyz for v in poly.unique_refs]
        midpoint = tuple((min(p[i] for p in points) + max(p[i] for p in points)) / 2
                         for i in range(3))
        app.frame_selection()
        for actual, expected in zip(app.center, midpoint):
            self.assertAlmostEqual(actual, expected)
        app.frame_model()
        self.assertAlmostEqual(app.extent, app._model_extent)
        self.assertFalse(app.model.dirty)

    def test_vertex_context_and_missing_selection_are_safe(self):
        app = self.app
        app.notebook.select(app.vertex_page)
        app.redraw()
        self.assertEqual(app.context_title.get(), "Nothing selected")
        self.assertEqual(str(app.frame_selected_button["state"]), "disabled")
        original_center = app.center
        app.frame_selection()
        self.assertEqual(app.center, original_center)
        ref = next(iter(app.model.vertices))
        app.choose(ref)
        self.assertEqual(app.context_title.get(), f"Vertex @{ref}")
        app.frame_selection()
        self.assertEqual(app.center, tuple(app.model.vertices[ref].xyz))
        self.assertFalse(app.model.dirty)


if __name__ == "__main__":
    unittest.main()
