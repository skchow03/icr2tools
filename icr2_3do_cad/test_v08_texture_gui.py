"""Desktop tests: texture assignments do not mutate the underlying 3DO."""
from pathlib import Path
import tempfile
import unittest
import tkinter as tk
from icr2_3do_cad import Editor
from test_v08_texture import create_test_mip
BASE=Path(__file__).parent

class TextureGuiTests(unittest.TestCase):
    def setUp(self):
        try:self.app=Editor()
        except tk.TclError:self.skipTest('Tk display unavailable')
        self.app.load_file(BASE/'fixtures'/'roadcar.3do')
        self.app.geometry('1200x820')
        self.app.update_idletasks()
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'checker.mip'
        create_test_mip(self.path)
        self.poly=next(p for p in self.app.model.polygons.values() if p.kind==2)
        self.app.selected_poly=self.poly.offset
    def tearDown(self):
        if hasattr(self,'app'):self.app.destroy()
        if hasattr(self,'temp'):self.temp.cleanup()
    def test_group_assignment_draws_textures_and_can_toggle(self):
        self.app.texture_manual[('group',self.poly.group)]=self.path
        self.app.redraw()
        self.assertTrue(self.app._texture_photos)
        self.assertIn('textured',self.app.preview_stats.get())
        self.app.show_textures.set(False);self.app.redraw()
        self.assertEqual(len(self.app._texture_photos),0)
        data,_=self.app.model.build_modified_bytes()
        self.assertEqual(data,self.app.model.raw)
    def test_real_ind96_mip_renders_and_keeps_binary_unmodified(self):
        real_mip=BASE/'fixtures'/'ind96.mip'
        self.app.texture_manual[('group',self.poly.group)]=real_mip
        self.app._refresh_texture_info()
        self.assertIn('128×165',self.app.texture_info.get())
        self.app.redraw()
        self.assertTrue(self.app._texture_photos)
        self.assertIn('textured',self.app.preview_stats.get())
        self.assertEqual(self.app.model.build_modified_bytes()[0],self.app.model.raw)

    def test_uv_change_affects_texture_projection_and_binary_only_uv(self):
        self.app.texture_manual[('group',self.poly.group)]=self.path
        vertex_ref=self.poly.unique_refs[0]
        vertex=self.app.model.vertices[vertex_ref]
        old=vertex.uv
        self.app.model.set_uv(vertex_ref,(old[0]+1,old[1]))
        self.app.redraw()
        self.assertTrue(self.app._texture_photos)
        new_data,_=self.app.model.build_modified_bytes()
        self.assertEqual(len(new_data),len(self.app.model.raw))
        self.assertNotEqual(new_data,self.app.model.raw)

if __name__=='__main__':unittest.main()
