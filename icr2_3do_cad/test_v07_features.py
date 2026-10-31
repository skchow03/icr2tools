"""Palette, back-to-front LIST ordering, perspective and unlit-default checks."""
import math
import os
import unittest
from pathlib import Path
from tkinter import TclError
from three_do import Model
from icr2_3do_cad import Editor, read_pcx_palette, rgbhex

BASE=Path(__file__).parent

class FileAndTraversalTests(unittest.TestCase):
    def test_bundled_game_palette(self):
        colors=read_pcx_palette(BASE/'gamepal.pcx')
        self.assertEqual(len(colors),256)
        self.assertEqual(colors[0],(0,0,0))
        self.assertEqual(colors[2],(227,0,0))
        self.assertTrue(all(0<=n<=255 for rgb in colors for n in rgb))

    def test_back_to_front_list_order_in_all_modes(self):
        m=Model(BASE/'fixtures'/'roadcar.3do')
        self.assertEqual(m.records[6580],11)
        expected=m.children[6580][:]
        self.assertGreater(len(expected),2)
        self.assertTrue(all(p in m.polygons for p in expected))
        m.root_offset=6580
        for mode in ('off','original','rebuilt'):
            observed,_,_=m.switched_polygons(None,(0,0,150000),mode)
            self.assertEqual(observed,expected)


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt', 'GUI test needs a desktop display')
class RendererTests(unittest.TestCase):
    def setUp(self):
        self.app=Editor(BASE/'fixtures'/'roadcar.3do')
        self.app.geometry('1100x820+10+10')
        self.app.update()
    def tearDown(self):
        self.app.destroy()

    def test_startup_palette_unlit_and_ortho(self):
        a=self.app
        self.assertEqual(a.projection.get(),'Orthographic')
        self.assertFalse(a.lighting.get())
        self.assertEqual(a.palette_source,'Default: gamepal.pcx')
        poly=next(p for p in a.model.polygons.values() if p.color==2)
        self.assertEqual(a._polygon_fill(poly),'#e30000')
        a.lighting.set(True)
        self.assertNotEqual(a._polygon_fill(poly),'#e30000')

    def test_perspective_depth_without_geometry_changes(self):
        a=self.app
        a.azimuth=math.radians(35)
        a.elevation=math.radians(25)
        a.frame_model()
        right,up,toward=a._basis()
        step=a.extent*0.2
        def point(x,d):
            return tuple(a.center[i]+x*right[i]+d*toward[i] for i in range(3))
        front=point(step,step)
        back=point(step,-step)
        a.projection.set('Orthographic')
        x1=a._project(front)[0]-a.canvas.winfo_width()/2
        x2=a._project(back)[0]-a.canvas.winfo_width()/2
        self.assertAlmostEqual(x1,x2,places=4)
        original=a.model.raw
        previous_lod=a.lod_distance.get()
        a.projection.set('Perspective (depth)')
        x1=a._project(front)[0]-a.canvas.winfo_width()/2
        x2=a._project(back)[0]-a.canvas.winfo_width()/2
        self.assertGreater(x1,x2*1.15)
        a.redraw()
        self.assertEqual(a.lod_distance.get(),previous_lod)
        self.assertEqual(a.model.build_modified_bytes()[0],original)
        self.assertGreater(len(a._screen_polygons),0)

    def test_list_order_reaches_canvas_without_global_depth_sort(self):
        a=self.app
        expected=a.model.children[6580][:]
        a.model.root_offset=6580
        a.lod_mode.set('All branches')
        a.bsp_mode.set('Off (show all)')
        for projection in ('Orthographic','Perspective (depth)'):
            a.projection.set(projection)
            a.redraw()
            self.assertEqual([off for off,_ in a._screen_polygons],expected)

if __name__=='__main__': unittest.main()
