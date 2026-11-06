"""Qt smoke/regression tests for the non-modal MIP UV reference window."""
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest

import numpy as np

from textures import build_atlas

DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
               or sys.platform in ("win32", "darwin"))


def make_mip(path, width, height, pixels):
    """Minimal valid, single-level Papyrus indexed MIP for the real decoder."""
    data = bytes(pixels)
    assert len(data) == width * height
    raw_size = 36 + len(data)
    Path(path).write_bytes(
        struct.pack("<6i", raw_size, 0, width, height, 1, 0)
        + struct.pack("<3i", 0, 0, 32) + data)


def palette_fixture():
    palette = np.zeros((256, 3), dtype=np.uint8)
    for i in range(256):
        palette[i] = (i, 255 - i, (i * 3) % 256)
    return palette


class MipBrowserResolverTests(unittest.TestCase):
    def test_resolved_source_paths_match_texture_atlas_with_reused_material(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            make_mip(root / "BODY.MIP", 4, 3, range(12))
            make_mip(root / "wheel.mip", 2, 2, range(4))
            model = SimpleNamespace(
                polygons={11: SimpleNamespace(kind=2),
                          22: SimpleNamespace(kind=2),
                          33: SimpleNamespace(kind=2)},
                polygon_materials={11: "BODY", 22: "wheel", 33: "body"},
                polygon_sources={},
                body_polygons=frozenset(),
            )
            atlas = build_atlas(model, root / "car.3d")
            self.assertEqual(atlas.loaded_names, ("BODY.MIP", "wheel.mip"))
            self.assertEqual(
                {Path(path).resolve() for path in atlas.loaded_paths},
                {(root / "BODY.MIP").resolve(),
                 (root / "wheel.mip").resolve()})
            self.assertEqual(len(atlas.polygon_rects), 3)


@unittest.skipUnless(DISPLAY, "Requires Qt desktop or Xvfb")
class MipBrowserUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            from icr2_3do_cad import Window
        except (ImportError, SystemExit) as exc:
            raise unittest.SkipTest(str(exc))
        cls.app = QApplication.instance() or QApplication([])
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        make_mip(cls.root / "BODY.MIP", 4, 3, range(12))
        make_mip(cls.root / "wheel.mip", 2, 2, range(4))
        from types import SimpleNamespace
        cls.model = SimpleNamespace(
            polygons={11: SimpleNamespace(kind=2),
                      22: SimpleNamespace(kind=2)},
            polygon_materials={11: "BODY", 22: "wheel"},
            polygon_sources={},
            body_polygons=frozenset(),
        )
        cls.atlas = build_atlas(cls.model, cls.root / "car.3d")
        cls.window = Window()

    @classmethod
    def tearDownClass(cls):
        cls.window.source_pane.reset()
        cls.window.close()
        cls.tmp.cleanup()

    def setUp(self):
        self.window.viewer._model = self.model
        self.window.viewer._atlas = self.atlas
        self.window.viewer._palette = palette_fixture()
        self.window._info = {"file": "car.3d"}
        from menus import update_model_actions
        update_model_actions(self.window)
        self.window.open_mip_browser()
        self.dialog = self.window.mip_browser
        self.app.processEvents()

    def tearDown(self):
        self.dialog.close()
        self.window.viewer._model = None
        self.window.viewer._atlas = None
        self.window.viewer._palette = None
        from menus import update_model_actions
        update_model_actions(self.window)

    def test_menu_opens_reusable_independent_window_listing_loaded_mips(self):
        from PySide6.QtCore import Qt
        self.assertFalse(self.dialog.isModal())
        self.assertTrue(self.dialog.isVisible())
        self.assertTrue(self.dialog.windowFlags() & Qt.WindowType.Window)
        # A parent-owned QDialog is kept above the main editor on Windows,
        # regardless of setModal(False). A truly independent top-level
        # window must have no parent/owner and no always-on-top flag.
        self.assertIsNone(self.dialog.parentWidget())
        self.assertIsNone(self.dialog.parent())
        self.assertFalse(
            bool(self.dialog.windowFlags() &
                 Qt.WindowType.WindowStaysOnTopHint))
        self.assertEqual(self.dialog.mips.count(), 2)
        self.assertEqual(self.dialog.mips.item(0).text(), "BODY.MIP")
        self.assertEqual(self.dialog.mips.item(1).text(), "wheel.mip")
        self.assertEqual(self.dialog.mips.currentRow(), 0)
        self.assertIn("4 × 3", self.dialog.details.text())
        previous = self.dialog
        self.dialog.close()
        self.window.open_mip_browser()
        self.assertIs(self.window.mip_browser, previous)
        self.assertTrue(previous.isVisible())

    def test_main_window_can_be_raised_while_mip_browser_stays_open(self):
        from PySide6.QtCore import Qt
        # Both are separate, regular top-level windows. Raising the editor
        # does not close or hide the UV reference and does not reparent it.
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()
        self.app.processEvents()
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.dialog.isVisible())
        self.assertIsNone(self.dialog.parentWidget())
        self.assertFalse(
            bool(self.dialog.windowFlags() &
                 Qt.WindowType.WindowStaysOnTopHint))
        self.window.hide()

    def test_palette_rgb_image_is_decoded_at_exact_texel(self):
        from mip_browser import mip_rgb_image
        image = mip_rgb_image(self.root / "BODY.MIP", palette_fixture())
        self.assertEqual((image.width(), image.height()), (4, 3))
        self.assertEqual(
            (image.pixelColor(2, 1).red(),
             image.pixelColor(2, 1).green(),
             image.pixelColor(2, 1).blue()),
            (6, 249, 18))

    def test_click_reads_top_origin_integer_uv_and_copy_to_clipboard(self):
        from PySide6.QtCore import QPointF, Qt, QEvent
        from PySide6.QtGui import QMouseEvent
        canvas = self.dialog.canvas
        self.assertIsNone(self.dialog.selected_uv)
        self.assertIsNone(canvas.texel_at(canvas.mapFromScene(QPointF(-1, -1))))
        self.assertEqual(
            canvas.texel_at(canvas.mapFromScene(QPointF(2.5, 1.5))),
            (2, 1))
        cursor = canvas.mapFromScene(QPointF(2.5, 1.5))
        click = QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(cursor),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)
        canvas.mousePressEvent(click)
        self.assertEqual(self.dialog.selected_uv, (2, 1))
        self.assertIn("U = 2", self.dialog.coordinates.text())
        self.assertIn("V = 1", self.dialog.coordinates.text())
        self.assertTrue(self.dialog.copy_button.isEnabled())
        self.dialog.copy_uv()
        self.assertEqual(self.app.clipboard().text(), "2, 1")

    def test_zoom_and_new_texture_reset_selection_and_palette_refresh(self):
        canvas = self.dialog.canvas
        old_zoom = canvas.zoom
        canvas.zoom_by(1.25)
        self.assertGreater(canvas.zoom, old_zoom)
        canvas.actual_size()
        self.assertAlmostEqual(canvas.zoom, 1)
        canvas.fit_image()
        self.dialog._clicked(1, 2)
        self.dialog.mips.setCurrentRow(1)
        self.assertIsNone(self.dialog.selected_uv)
        self.assertFalse(self.dialog.copy_button.isEnabled())
        self.assertIn("2 × 2", self.dialog.details.text())
        # Palette changes refresh the currently shown texture without
        # recreating the dialog or losing the selected MIP.
        self.dialog.canvas.zoom_by(1.25)
        zoom_before = self.dialog.canvas.zoom
        self.dialog.canvas.mark_texel(1, 1)
        self.dialog._clicked(1, 1)
        updated = palette_fixture()
        updated[0] = [7, 8, 9]
        self.window.viewer._palette = updated
        self.window._refresh_mip_browser()
        self.app.processEvents()
        self.assertEqual(self.dialog.selected_uv, (1, 1))
        self.assertAlmostEqual(self.dialog.canvas.zoom, zoom_before)
        self.assertEqual(self.dialog.mips.currentRow(), 1)
        self.assertEqual(
            self.dialog.canvas._item.pixmap().toImage().pixelColor(0, 0).getRgb()[:3],
            (7, 8, 9))

    def test_browser_rebuilds_when_model_texture_assignments_change(self):
        from types import SimpleNamespace
        from textures import TextureAtlas
        self.dialog.mips.setCurrentRow(1)
        self.assertEqual(self.dialog.mips.currentItem().text(), "wheel.mip")
        new_atlas = TextureAtlas(
            pixels=np.zeros((1, 1), dtype=np.uint8),
            polygon_rects={},
            loaded_names=("BODY.MIP",),
            loaded_paths=(str(self.root / "BODY.MIP"),),
            missing_names=("missing.mip",))
        self.window.viewer._atlas = new_atlas
        self.window._refresh_mip_browser()
        self.assertEqual(self.dialog.mips.count(), 1)
        self.assertEqual(self.dialog.mips.currentItem().text(), "BODY.MIP")
        self.assertIn("missing.mip", self.dialog.summary.text())

    def test_menu_unavailable_until_model_loaded(self):
        from menus import update_model_actions
        self.window.viewer._model = None
        update_model_actions(self.window)
        self.assertFalse(self.window.menu_actions["mip_browser"].isEnabled())
        self.window.viewer._model = self.model
        update_model_actions(self.window)
        self.assertTrue(self.window.menu_actions["mip_browser"].isEnabled())


if __name__ == "__main__":
    unittest.main()
