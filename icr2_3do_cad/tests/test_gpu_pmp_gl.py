"""Real OpenGL 3.3 framebuffer tests for PMP/PMP2 sprites (Xvfb)."""
import os
import sys
import unittest
from pathlib import Path

import numpy as np

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or
                   os.environ.get("WAYLAND_DISPLAY") or
                   sys.platform in ("win32", "darwin"))

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


@unittest.skipUnless(HAS_DISPLAY, "Qt/OpenGL needs a desktop or Xvfb")
class GPURealPMPRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtGui import QSurfaceFormat
            from PySide6.QtWidgets import QApplication
            from gpu_viewer.main import GLViewport
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
        self.view = self.GLViewport()
        self.view.resize(720, 540)
        self.view.show()
        self.app.processEvents()
        self.assertTrue(self.view.context().isValid())

    def tearDown(self):
        self.view.shutdown_gl()
        self.view.close()
        self.app.processEvents()

    def install_model(self, name):
        from three_do import Model
        from gpu_viewer.scene import build_scene
        from gpu_viewer.mesh import make_mesh
        from gpu_viewer.sprites import prepare_scene_sprites
        from gpu_viewer.textures import build_atlas, load_palette

        source = name if isinstance(name, Path) else FIXTURES / name
        model = Model(source, associate_planes=False)
        scene = build_scene(model, objects_folder=FIXTURES)
        scene.sprite_resources = prepare_scene_sprites(
            scene, objects_folder=FIXTURES)
        scene.geometry.sprite_bounds = scene.sprite_resources.bounds_points
        palette = load_palette(ROOT / "gamepal.pcx")
        atlas = build_atlas(scene.geometry, source)
        mesh = make_mesh(scene.geometry, palette.astype(np.float32)/255, atlas)
        self.view.set_mesh(mesh, model, atlas, palette, scene)
        self.view.set_view("Front")
        self.app.processEvents()
        self.assertIsNotNone(self.view._sprite_renderer)
        self.assertEqual(
            len(self.view._sprite_renderer.textures),
            len(scene.sprite_resources.images))
        return scene

    def screenshot(self):
        from PySide6.QtGui import QImage
        self.app.processEvents()
        image = self.view.grabFramebuffer()
        self.assertFalse(image.isNull())
        image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        raw = np.frombuffer(
            image.bits(), dtype=np.uint8, count=image.sizeInBytes())
        return raw.reshape(image.height(), image.bytesPerLine())[
            :, :image.width() * 4].reshape(image.height(), image.width(), 4).copy()

    def test_sprite_only_helmet_renders_actual_indexed_pixels(self):
        scene = self.install_model("helmet.3do")
        self.assertEqual(len(scene.sprite_resources.images), 8)
        image_on = self.screenshot()
        self.assertEqual(len(self.view._sprite_events), 1)
        self.assertEqual(self.view._visibility_info["pmp_sprites"], 1)
        self.view.sprites_enabled = False
        self.view.update()
        image_off = self.screenshot()
        changed = np.any(image_on[..., :3] != image_off[..., :3], axis=2)
        self.assertGreater(int(changed.sum()), 25)
        self.assertEqual(self.view._mesh.polygon_count, 0)
        self.assertEqual(self.view._mesh.triangle_count, 0)

        # The existing Textures toggle hides PMP just as in CPU CAD.
        self.view.sprites_enabled = True
        self.view.textures_enabled = False
        self.view.update()
        no_textures = self.screenshot()
        self.assertTrue(np.array_equal(no_textures, image_off))

        # The SAME sprite index texture must recolor from the shared palette
        # without uploading a new geometry VBO or re-decoding PMP files.
        self.view.textures_enabled = True
        before_vbo = self.view._vbo
        before_textures = dict(self.view._sprite_renderer.textures)
        recolored = 255 - self.view._palette.copy()
        self.view.set_palette(recolored)
        new_frame = self.screenshot()
        self.assertGreater(int(np.any(
            new_frame[..., :3] != image_on[..., :3], axis=2).sum()), 25)
        self.assertEqual(self.view._vbo, before_vbo)
        self.assertEqual(self.view._sprite_renderer.textures, before_textures)

    def test_pmp2_sprite_only_model_renders(self):
        self.install_model("helmetp.3do")
        self.assertEqual(self.view._mesh.polygon_count, 0)
        on = self.screenshot()
        self.assertEqual(len(self.view._sprite_events), 1)
        self.view.sprites_enabled = False
        self.view.update()
        off = self.screenshot()
        self.assertGreater(int(np.any(on[..., :3] != off[..., :3],
                                      axis=2).sum()), 25)

    def test_scenery_pmp_and_pmp2_vertical_midpoint_equals_anchor_z(self):
        """An asymmetrically painted tree straddles a Z=0 3DO anchor.

        Tree-like sprites occupy canvas rows 7..127. The former fixed
        source-row-128 origin put the entire tree ABOVE the anchor. Both
        PMP flavors must instead paint equal heights above and below it.
        """
        import struct
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            spans = b"".join(
                bytes((y, 66, 188, 47)) for y in range(7, 128))
            # Width=122, height=121, min_x=66, min_y=7.
            # This is deliberately NOT tree2's 5b7baffb value.
            (folder / "TREE1.PMP").write_bytes(
                bytes.fromhex("7a79bef9") +
                struct.pack("<II", len(spans), 30) + spans)
            for sprite_kind in (3, 18):  # PMP and PMP2 share the geometry
                with self.subTest(sprite_kind=sprite_kind):
                    model_path = folder / f"tree{sprite_kind}.3do"
                    model_path.write_bytes(
                        struct.pack("<5i", 32, 16, 0, 1, 0) +
                        b"tree1\x00\x00\x00" +
                        struct.pack("<8i", 0, 0, 0, 0,
                                    -(1 << 31) + sprite_kind,
                                    0, 240000, 0))
                    scene = self.install_model(model_path)
                    self.assertEqual(len(scene.sprite_resources.placements), 1)
                    self.assertEqual(len(scene.sprite_resources.images), 1)
                    self.assertEqual(scene.sprite_resources.warnings, ())
                    placement = next(iter(scene.sprite_resources.placements.values()))
                    self.assertEqual(placement.xyz, (0.0, 0.0, 0.0))
                    self.assertEqual(placement.bounds, (66, 7, 188, 128))
                    on = self.screenshot()
                    self.assertEqual(self.view._visibility_info["pmp_sprites"], 1)
                    self.view.sprites_enabled = False
                    self.view.update()
                    off = self.screenshot()
                    mask = np.any(on[..., :3] != off[..., :3], axis=2)
                    self.assertGreater(int(mask.sum()), 25)
                    y, _ = np.nonzero(mask)
                    # Sprite-only model's symmetric mesh bounds and Front
                    # projection put the raw Z=0 anchor at screen mid-height.
                    anchor_y = on.shape[0] / 2.0
                    self.assertGreater(anchor_y - int(y.min()), 12)
                    self.assertGreater(int(y.max()) - anchor_y, 12)
                    self.assertAlmostEqual(
                        (float(y.min()) + float(y.max())) / 2.0,
                        anchor_y, delta=3.0)
                    self.view.sprites_enabled = True
                    self.view.update()

    def test_referenced_helmet_drawn_inside_car_scene(self):
        scene = self.install_model("indycar.3do")
        self.assertGreater(scene.loaded_instances, 0)
        self.assertEqual(len(scene.sprite_resources.placements), 8)
        # Center on transformed helmet placement at a useful zoom level.
        placement = next(iter(scene.sprite_resources.placements.values()))
        scale = self.view._mesh.scale
        self.view.target = (
            np.asarray(placement.xyz) - np.asarray(self.view._mesh.center)
        ) / scale
        self.view.half_height = max(
            .04, abs(placement.size) / scale * 1.3)
        self.view.distance = 4.0
        self.view.invalidate_visibility()
        on = self.screenshot()
        self.assertEqual(self.view._visibility_info["pmp_sprites"], 1)
        self.assertEqual(len(self.view._sprite_events), 1)
        self.assertGreater(self.view._index_count, 0)
        self.view.sprites_enabled = False
        self.view.update()
        off = self.screenshot()
        self.assertGreater(int(np.any(on[..., :3] != off[..., :3],
                                      axis=2).sum()), 15)


if __name__ == "__main__":
    unittest.main()
