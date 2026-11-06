"""Offscreen integration test: source POLY highlighting obeys RES selection.

Run under Xvfb with a working desktop OpenGL 3.3 implementation.
"""
from __future__ import annotations

import sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtGui import QSurfaceFormat, QTextCursor
from PySide6.QtWidgets import QApplication

from n3_compile import compile_n3_text
from icr2_3do_cad import Window
from mesh import make_mesh
from scene import build_scene
from textures import load_palette, build_atlas

SOURCE = """3D VERSION 3.0;
a: [<-200,-200,0>];
b: [<200,-200,0>];
c: [<0,200,0>];
near: POLY <44> {a,b,c};
far: POLY <55> {a,c,b};
lod: SWITCH DISTANCE (a) > {(1200 ? far), (0 ? near)};
root: LIST {lod};
"""


def run():
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication([sys.argv[0]])
    window = Window()
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    try:
        window.resize(1200, 820)
        window.show()
        app.processEvents()
        path = ROOT / "source_visibility_smoke.3d"
        model, _ = compile_n3_text(SOURCE, path, associate_planes=False)
        scene = build_scene(model)
        palette = load_palette(window.palette_path)
        atlas = build_atlas(scene.geometry, path)
        mesh = make_mesh(scene.geometry, palette.astype(np.float32) / 255.0,
                         atlas)
        window.viewer.set_mesh(mesh, model, atlas, palette, scene)
        window._configure_switch_distance(scene)
        window.source_pane.set_source(SOURCE, path)
        window.source_toggle.setChecked(True)
        app.processEvents()
        assert window.lod_slider.maximum() == 1200
        window.lod_mode_combo.setCurrentIndex(
            window.lod_mode_combo.findData("manual"))
        assert window.viewer.lod_distance == 0

        far_offset = model.n3_label_offsets["far"]
        near_offset = model.n3_label_offsets["near"]
        view = window.viewer
        # Establish the baseline framebuffer with the near-only branch drawn.
        base = view.grabFramebuffer()
        assert not base.isNull(), "No OpenGL framebuffer"
        assert near_offset in view._visible_set, "Near LOD was not selected"
        assert far_offset not in view._visible_set, "Far LOD selected too soon"
        cursor = QTextCursor(
            window.source_pane.editor.document().findBlockByNumber(5))
        window.source_pane.editor.setTextCursor(cursor)
        assert view.inspection_kind == "polygon"
        assert view.inspection_offset == far_offset
        hidden = view.grabFramebuffer()
        assert not hidden.isNull()
        assert window.source_pane._polygon_visible is False
        banner = view.visibility_banner
        assert banner.isVisible(), "No Qt warning widget shown for hidden source POLY"
        assert banner.text().startswith("POLY NOT VISIBLE\n")
        assert "SWITCH DISTANCE" in banner.text()
        assert banner.width() > 300 and banner.height() >= 70
        # Qt renders text independently of raw OpenGL. Inspect actual widget
        # pixels for substantial white glyph coverage, not speckles/streaks
        # drawn in the GL framebuffer (the reported regression).
        widget_image = banner.grab().toImage()
        assert not widget_image.isNull(), "Warning Qt widget did not paint"
        white_pixels = sum(
            widget_image.pixelColor(x, y).red() >= 220 and
            widget_image.pixelColor(x, y).green() >= 220 and
            widget_image.pixelColor(x, y).blue() >= 220
            for y in range(8, widget_image.height() - 8)
            for x in range(8, widget_image.width() - 8))
        assert white_pixels >= 80, (
            f"Warning lettering was not rendered legibly: {white_pixels} white pixels")
        banner.grab().save("gpu_visibility_warning.png")
        # The OpenGL framebuffer itself must remain byte-identical to the
        # inactive-branch baseline; only the independent Qt label changed.
        for y in range(5, min(base.height(), hidden.height()), 40):
            for x in range(20, min(base.width(), hidden.width()), 40):
                assert (hidden.pixelColor(x, y).rgba() ==
                        base.pixelColor(x, y).rgba()), (
                            f"Hidden POLY was painted at screen pixel ({x}, {y})")

        # Dragging to the highest branch threshold makes far the selected LOD.
        window.lod_slider.setValue(1200)
        assert window.lod_spin.value() == 1200
        assert window.viewer.lod_distance == 1200
        revealed = view.grabFramebuffer()
        assert far_offset in view._visible_set
        assert near_offset not in view._visible_set
        assert window.source_pane._polygon_visible is True
        assert banner.isHidden(), (
            "Qt visibility warning was not removed when the branch became selected")
        # Selecting near at the far distance must now show the same warning.
        window.source_pane.editor.setTextCursor(QTextCursor(
            window.source_pane.editor.document().findBlockByNumber(4)))
        assert view.inspection_offset == near_offset
        other = view.grabFramebuffer()
        assert banner.isVisible(), "Inactive near LOD did not show its warning"
        assert "SWITCH DISTANCE" in banner.text()
        assert window.source_pane._polygon_visible is False
        assert other.pixelColor(15, 15).rgba() == revealed.pixelColor(15, 15).rgba()
        print("Source polygon respects SWITCH DISTANCE and shows warnings")
    finally:
        window.close()
        app.processEvents()
        app.quit()


if __name__ == "__main__":
    run()
