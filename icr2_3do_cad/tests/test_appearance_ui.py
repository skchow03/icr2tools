"""Qt tests for live Source pane and viewport appearance (Xvfb/desktop)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HAS_DISPLAY = bool(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    or sys.platform in ("win32", "darwin")
)
SOURCE = """3D VERSION 3.0;
a: [<0,0,0>];
b: [<100,0,0>];
c: [<0,100,0>];
surface: POLY <44> {a,b,c};
root: LIST {surface};
"""


@unittest.skipUnless(HAS_DISPLAY, "Requires a desktop or xvfb-run")
class GPUAppearanceUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtCore import QSettings
            from PySide6.QtWidgets import QApplication
            from PySide6.QtGui import QPalette
            import icr2_3do_cad as main
        except (ImportError, SystemExit) as error:
            raise unittest.SkipTest(f"3DO CAD dependencies unavailable: {error}")
        cls.temp = tempfile.TemporaryDirectory()
        cls.settings_file = str(Path(cls.temp.name) / "appearance.ini")
        cls.real_settings = QSettings
        cls.patch_settings = patch.object(
            main, "QSettings", side_effect=lambda *args: QSettings(
                cls.settings_file, QSettings.Format.IniFormat))
        cls.patch_settings.start()
        cls.app = QApplication.instance() or QApplication([])
        cls.window = main.Window()
        cls.QPalette = QPalette
        cls.main = main

    @classmethod
    def tearDownClass(cls):
        cls.window.source_pane.reset()
        cls.window.close()
        cls.patch_settings.stop()
        cls.temp.cleanup()

    def test_dark_source_palette_is_not_dependent_on_desktop_theme(self):
        from appearance import DARK_COLORS
        pane = self.window.source_pane
        pane.set_appearance_colors(DARK_COLORS)
        palette = pane.editor.palette()
        self.assertEqual(
            palette.color(self.QPalette.ColorRole.Base).name().upper(),
            DARK_COLORS["source_background"])
        self.assertEqual(
            palette.color(self.QPalette.ColorRole.Text).name().upper(),
            DARK_COLORS["source_text"])
        self.assertEqual(
            pane.highlighter.formats["keyword"].foreground().color().name().upper(),
            DARK_COLORS["source_keyword"])

    def test_live_customization_updates_editor_filtered_rows_and_viewport(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QTextCursor
        from appearance import DARK_COLORS
        pane = self.window.source_pane
        pane.set_source(SOURCE, Path("colors.3d"))
        customized = dict(DARK_COLORS,
                          source_background="#202D40",
                          source_keyword="#C0E0FF",
                          source_visible_background="#204A3C",
                          viewport_background="#445566",
                          viewport_wire="#99AAFF",
                          viewport_selected_wire="#FF9955",
                          viewport_vertex_dot="#EEFF22",
                          viewport_vertex_outline="#111122")
        self.window._set_appearance_colors(customized)
        self.assertEqual(pane.editor.palette().color(
            self.QPalette.ColorRole.Base).name(), "#202d40")
        self.assertEqual(pane.highlighter.formats[
            "keyword"].foreground().color().name(), "#c0e0ff")
        for actual, expected in zip(
                self.window.viewer._wire_color_rgb("viewport_wire"),
                (0.6, 2/3, 1.0)):
            self.assertAlmostEqual(actual, expected, places=5)
        outline, dot = self.window.viewer._vertex_marker_colors()
        self.assertEqual(outline.name(), "#111122")
        self.assertEqual(dot.name(), "#eeff22")
        self.assertEqual(self.window.viewer.colors[
            "viewport_background"], "#445566")
        # Inspect a standalone SourcePane: the Window intentionally clears
        # POLY visibility when no renderable model has been opened.
        from source_tab import SourcePane
        inspection = SourcePane()
        try:
            inspection.set_source(SOURCE, Path("colors.3d"))
            inspection.set_appearance_colors(customized)
            block = inspection.editor.document().findBlockByNumber(4)
            self.assertTrue(block.isValid())
            self.assertTrue(inspection.ready)
            self.assertFalse(inspection.pending)
            self.assertEqual(inspection._source_index.at_line(4),
                             ("polygon", "surface"))
            inspection.editor.setTextCursor(QTextCursor(block))
            self.assertEqual(inspection.editor.textCursor().blockNumber(), 4)
            self.assertEqual(inspection.current_target(),
                             ("polygon", "surface"))
            inspection.set_polygon_visibility(True)
            selections = inspection.editor.extraSelections()
            self.assertTrue(selections)
            selected_format = selections[0].format
            self.assertEqual(
                selected_format.background().color().name(), "#204a3c")
            inspection._only_filter("POLY")
            index = inspection.filtered_model.index(0)
            self.assertEqual(inspection.filtered_model.data(
                index, Qt.ItemDataRole.BackgroundRole).name(), "#204a3c")
        finally:
            inspection.close()
        settings = self.real_settings(
            self.settings_file, self.real_settings.Format.IniFormat)
        self.assertEqual(settings.value("appearance/viewport_wire"), "#99AAFF")
        self.assertEqual(settings.value("appearance/source_background"), "#202D40")

    def test_presets_can_be_applied_and_reset_without_restarting(self):
        from appearance import DARK_COLORS, LIGHT_COLORS
        from appearance_dialog import AppearanceDialog
        dialog = AppearanceDialog(
            self.window.appearance_colors,
            self.window._set_appearance_colors, self.window)
        try:
            dialog._set_colors(LIGHT_COLORS)
            self.assertEqual(
                self.window.source_pane.editor.palette().color(
                    self.QPalette.ColorRole.Base).name(), "#ffffff")
            self.assertEqual(self.window.viewer.colors["viewport_wire"],
                             LIGHT_COLORS["viewport_wire"])
            dialog._set_colors(DARK_COLORS)
            self.assertEqual(self.window.appearance_colors, DARK_COLORS)
            self.assertEqual(self.window.source_pane.highlighter.formats[
                "label"].foreground().color().name().upper(),
                DARK_COLORS["source_label"])
        finally:
            dialog.close()
            self.window.source_pane.reset()


if __name__ == "__main__":
    unittest.main()
