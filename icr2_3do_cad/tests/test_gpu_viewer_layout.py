"""UI smoke tests for the GPU viewer's viewport-first layout.

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
            from PySide6.QtWidgets import QApplication, QScrollArea
            from gpu_viewer.main import Window
        except (ImportError, SystemExit) as error:
            raise unittest.SkipTest(f"GPU viewer requirements unavailable: {error}")
        cls.app = QApplication.instance() or QApplication([])
        cls.QScrollArea = QScrollArea
        cls.window = Window()

    @classmethod
    def tearDownClass(cls):
        cls.window.close()

    def test_document_area_only_contains_viewport_and_source(self):
        # No toolbar, sidebar or source Help tab occupies the main window.
        main_layout = self.window.centralWidget().layout()
        self.assertEqual(main_layout.count(), 1)
        self.assertEqual(self.window.editor_splitter.count(), 2)
        self.assertIs(self.window.editor_splitter.widget(0), self.window.viewport_panel)
        self.assertIs(self.window.editor_splitter.widget(1), self.window.source_pane)
        self.assertIs(self.window.viewport_layout.itemAt(0).widget(),
                      self.window.distance_bar)
        self.assertIs(self.window.viewport_layout.itemAt(1).widget(),
                      self.window.viewer)
        self.assertIs(self.window.lod_slider.parentWidget(),
                      self.window.distance_bar)
        self.assertIs(self.window.lod_mode_combo.parentWidget(),
                      self.window.distance_bar)
        self.assertIs(self.window.lod_spin.parentWidget(),
                      self.window.distance_bar)
        self.assertTrue(self.window.source_toggle.isChecked())
        self.assertFalse(self.window.source_pane.isHidden())

    def test_former_sidebar_sections_are_nonmodal_dialogs(self):
        for key in ("model", "display", "assets", "advanced"):
            with self.subTest(key=key):
                dialog = self.window.settings_dialogs[key]
                self.assertFalse(dialog.isModal())
                self.assertTrue(dialog.isHidden())
                self.assertIsNotNone(dialog.findChild(
                    self.QScrollArea))
        self.window.open_settings_dialog("model", workspace=1)
        self.assertEqual(self.window.workspace_tabs.currentIndex(), 1)
        self.assertFalse(self.window.settings_dialogs["model"].isHidden())
        self.window.settings_dialogs["model"].close()
        self.window.workspace_tabs.setCurrentIndex(2)

    def test_mip_uv_repeat_is_default_and_can_be_disabled(self):
        checkbox = self.window.repeat_uv
        self.assertTrue(checkbox.isChecked())
        self.assertTrue(self.window.viewer.texture_repeat)
        checkbox.setChecked(False)
        self.assertFalse(self.window.viewer.texture_repeat)
        checkbox.setChecked(True)
        self.assertTrue(self.window.viewer.texture_repeat)

    def test_track_window_counts_and_adaptive_mode_are_available(self):
        # No TRK is loaded in this layout smoke test. The adaptive choice
        # is visible but disabled until validated DLONG metadata arrives.
        selector = self.window.track_detail_combo
        adaptive = selector.findData("window")
        self.assertGreaterEqual(adaptive, 0)
        self.assertFalse(selector.model().item(adaptive).isEnabled())
        self.assertEqual(selector.currentData(), "hi")
        controls = self.window.track_window_spins
        self.assertEqual([spin.value() for spin in controls], [8, 5, 3])
        self.assertTrue(all(not spin.isEnabled() for spin in controls))
        self.assertEqual(self.window.viewer.track_window_counts, (8, 5, 3))

        # The edits change the shared rendering state without recompiling.
        controls[0].setValue(9)
        self.assertEqual(self.window.viewer.track_window_counts, (9, 5, 3))
        controls[1].setValue(0)
        self.assertEqual(self.window.viewer.track_window_counts, (9, 0, 3))
        controls[0].setValue(8)
        controls[1].setValue(5)
        self.assertEqual(self.window.viewer.track_window_counts, (8, 5, 3))

    def test_switch_distance_slider_and_modes(self):
        from n3_compile import compile_n3_text
        from gpu_viewer.scene import build_scene

        text = """3D VERSION 3.0;
a: [<0,0,0>];
b: [<100,0,0>];
c: [<0,100,0>];
near_poly: POLY <44> {a,b,c};
far_poly: POLY <55> {a,c,b};
res: SWITCH DISTANCE (a) > {(1200 ? far_poly), (0 ? near_poly)};
root: LIST {res};
"""
        model, _ = compile_n3_text(text, "distance_ui.3d",
                                   associate_planes=False)
        self.window._configure_switch_distance(build_scene(model))
        selector = self.window.lod_mode_combo
        slider = self.window.lod_slider
        spin = self.window.lod_spin
        self.assertEqual(slider.minimum(), 0)
        self.assertEqual(slider.maximum(), 1200)
        self.assertEqual(spin.maximum(), 1200)
        self.assertTrue(slider.isEnabled())
        self.assertTrue(spin.isEnabled())
        self.assertEqual(selector.currentData(), "auto")
        self.assertEqual(self.window.viewer.lod_distance, "auto")

        # Moving the slider engages manual mode, and its exact value is shown.
        slider.setValue(575)
        self.assertEqual(selector.currentData(), "manual")
        self.assertEqual(spin.value(), 575)
        self.assertEqual(self.window.viewer.lod_distance, 575)
        spin.setValue(1199)
        self.assertEqual(slider.value(), 1199)
        self.assertEqual(self.window.viewer.lod_distance, 1199)

        selector.setCurrentIndex(selector.findData("all"))
        self.assertIsNone(self.window.viewer.lod_distance)
        selector.setCurrentIndex(selector.findData("auto"))
        self.assertEqual(self.window.viewer.lod_distance, "auto")

        # Loading another object recalculates/clamps the available range.
        self.window._configure_switch_distance(build_scene(
            compile_n3_text(text.replace("1200", "200"), "small.3d",
                            associate_planes=False)[0]))
        self.assertEqual(slider.maximum(), 200)
        self.assertEqual(slider.value(), 200)
        self.assertEqual(spin.value(), 200)
        self.assertEqual(self.window.viewer.lod_distance, "auto")
        self.window._configure_switch_distance(None)
        self.assertEqual(slider.maximum(), 0)
        self.assertFalse(slider.isEnabled())
        self.assertFalse(spin.isEnabled())

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
