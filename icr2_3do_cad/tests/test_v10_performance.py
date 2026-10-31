"""Regression tests for quality reduction, tile caching and motion scheduling."""
from pathlib import Path
import time
import unittest
from PIL import Image
from icr2_3do_cad import Editor
from texture_preview import rasterize_polygon
BASE=Path(__file__).resolve().parents[1]

class PerformanceRasterTests(unittest.TestCase):
    def test_quality_reduction_keeps_full_tile_bounds(self):
        img=Image.new('P',(16,16),color=4)
        colors=[(i,i,0) for i in range(256)]
        verts=[(4,7,1,0,0),(59,7,1,15,0),(59,37,1,15,15),(4,37,1,0,15)]
        full=rasterize_polygon(img,colors,verts,(100,70),sample_scale=1.)
        fast=rasterize_polygon(img,colors,verts,(100,70),sample_scale=.4)
        self.assertEqual(full[1:],fast[1:])
        self.assertEqual(full[0].size,fast[0].size)
        self.assertEqual(full[0].getpixel((12,12)),fast[0].getpixel((12,12)))
        self.assertEqual(fast[0].getpixel((12,12))[3],255)
    def test_quality_setting_boundaries(self):
        img=Image.new('P',(4,4)); colors=[(0,0,0)]*256
        v=[(0,0,1,0,0),(5,0,1,3,0),(0,5,1,0,3)]
        with self.assertRaises(ValueError):
            rasterize_polygon(img,colors,v,(10,10),sample_scale=.1)

class EditorPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.app=Editor()
        self.app.load_file(BASE/'fixtures'/'roadcar.3do')
        self.app.geometry('1200x850')
        self.app.update_idletasks()
        poly=next(p for p in self.app.model.polygons.values() if p.kind==2)
        self.app.texture_manual[('group',poly.group)]=BASE/'fixtures'/'ind96.mip'
        self.poly=poly
    def tearDown(self):
        self.app.destroy()
    def test_unchanged_texture_tile_reused(self):
        app=self.app
        app.redraw()
        before={k:v[0] for k,v in app._texture_tile_cache.items()}
        self.assertGreater(len(before),0)
        app.redraw()
        self.assertEqual({k:v[0] for k,v in app._texture_tile_cache.items()},before)
        self.assertTrue(app._texture_photos)
        self.assertEqual(app.model.build_modified_bytes()[0],app.model.raw)
    def test_cache_refreshes_after_uv_change_and_projection(self):
        app=self.app;app.redraw()
        old=set(app._texture_tile_cache)
        ref=self.poly.unique_refs[0]
        uv=app.model.vertices[ref].uv
        app.model.set_uv(ref,(uv[0]+1,uv[1]))
        app.redraw()
        self.assertTrue(set(app._texture_tile_cache)-old)
        before=set(app._texture_tile_cache)
        app.projection.set('Perspective (depth)')
        app.redraw()
        self.assertTrue(set(app._texture_tile_cache)-before)
    def test_interactive_coalescing_refines_when_idle(self):
        app=self.app
        self.assertEqual(app.texture_quality.get(),'Balanced (75%)')
        self.assertEqual(app._texture_sampling_scale(),.75)
        for _ in range(12):app.request_view_redraw()
        self.assertTrue(app._interactive_view)
        self.assertEqual(app._texture_sampling_scale(),.4)
        self.assertIsNotNone(app._pending_view_redraw)
        app.update()
        # The coalesced redraw can take longer than the 180ms idle timer
        # on slow/loaded CI runners. Either state is valid after it finishes.
        time.sleep(.035);app.update()
        self.assertIsNone(app._pending_view_redraw)
        self.assertEqual(app._texture_sampling_scale(),
                         .4 if app._interactive_view else .75)
        app.finish_view_motion()
        self.assertFalse(app._interactive_view)
        self.assertEqual(app._texture_sampling_scale(),.75)
        self.assertIsNone(app._pending_refine)
    def test_fast_full_quality_selection(self):
        app=self.app
        app.texture_quality.set('Full (100%)')
        self.assertEqual(app._texture_sampling_scale(),1.)
        app._interactive_view=True
        self.assertEqual(app._texture_sampling_scale(),.55)
        app._interactive_view=False
        app.texture_quality.set('Fast (50%)')
        self.assertEqual(app._texture_sampling_scale(),.5)

if __name__=='__main__':unittest.main()
