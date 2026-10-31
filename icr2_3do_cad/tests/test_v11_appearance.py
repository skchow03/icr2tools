"""Car RECOLOR wrapper fixtures and Tk integration regression coverage."""
from pathlib import Path
import tempfile
import struct
import unittest
import tkinter as tk
from unittest.mock import patch

from car_appearance import read_car_appearance, locate_base_geometry, AppearanceError
from icr2_3do_cad import Editor
from three_do import Model

BASE=Path(__file__).resolve().parents[1]
FIXTURES=BASE/'fixtures'

class CompanionFormat(unittest.TestCase):
    def test_real_wrapper_reads_68_recolors(self):
        a=read_car_appearance(FIXTURES/'ind96.3do')
        self.assertEqual(a.geometry_name,'indycar')
        self.assertEqual(a.texture_name,'ind96')
        self.assertEqual(len(a.mapping),68)
        self.assertEqual(a.map_color(1),49)
        self.assertEqual(a.map_color(7),153)
        self.assertEqual(a.map_color(32),32) # unmapped base slot is unchanged
        self.assertEqual(a.map_color(85),52)
        self.assertEqual(a.raw,(FIXTURES/'ind96.3do').read_bytes())
    def test_base_geometry_is_not_wrapper(self):
        with self.assertRaises(AppearanceError):
            read_car_appearance(FIXTURES/'indycar.3do')
    def test_wrapper_root_material_points_to_zero_valid_record(self):
        a=read_car_appearance(FIXTURES/'ind96.3do')
        self.assertEqual(struct.unpack_from('<i',a.raw,len(a.raw)-12)[0],0) # MIP idx
        self.assertEqual(struct.unpack_from('<i',a.raw,len(a.raw)-4)[0],0) # RECOLOR at body offset 0
    def test_find_base_geometry_fallback(self):
        a=read_car_appearance(FIXTURES/'ind96.3do')
        self.assertEqual(locate_base_geometry(a),FIXTURES/'indycar.3do')
    def test_bad_recolor_is_rejected(self):
        raw=bytearray((FIXTURES/'ind96.3do').read_bytes())
        struct.pack_into('<i',raw,36+8+4,999)  # first destination is not a palette index
        with tempfile.TemporaryDirectory() as directory:
            f=Path(directory)/'broken.3do';f.write_bytes(raw)
            with self.assertRaises(AppearanceError):read_car_appearance(f)
    def test_truncated_recolor_rejected(self):
        raw=bytearray((FIXTURES/'ind96.3do').read_bytes())
        struct.pack_into('<i',raw,36+4,9000)
        with tempfile.TemporaryDirectory() as directory:
            f=Path(directory)/'broken.3do';f.write_bytes(raw)
            with self.assertRaises(AppearanceError):read_car_appearance(f)

class CompanionUI(unittest.TestCase):
    def setUp(self):
        try:self.app=Editor()
        except tk.TclError:self.skipTest('Tk display unavailable')
        self.app.geometry('1200x840')
        self.app.update_idletasks()
    def tearDown(self):
        if hasattr(self,'app'):self.app.destroy()
    def test_open_wrapper_direct_and_show_recolored_polys(self):
        self.assertTrue(self.app.load_file(FIXTURES/'ind96.3do'))
        self.assertEqual(self.app.model.path.name,'indycar.3do')
        self.assertEqual(self.app.appearance.path.name,'ind96.3do')
        poly=next(p for p in self.app.model.polygons.values() if p.color==1)
        self.assertEqual(self.app.effective_color(poly),49)
        self.assertEqual(self.app._color(poly),self.app.palette[49])
        self.assertIn('1 → 49',self.app._color_label(poly))
        self.assertEqual(self.app.model.build_modified_bytes()[0],self.app.model.raw)
        self.assertIn('68 RECOLOR slots',self.app.appearance_info.get())
    def test_companion_mip_loaded_without_manual_assign(self):
        self.assertTrue(self.app.load_file(FIXTURES/'ind96.3do'))
        poly=next(p for p in self.app.model.polygons.values() if p.kind==2)
        texpath=self.app._texture_path_for(poly)
        self.assertIsNotNone(texpath)
        self.assertEqual(texpath.name,'ind96.mip')
        img=self.app.get_polygon_texture(poly)
        self.assertEqual((img.width,img.height),(128,165))
        self.app.lod_mode.set('All branches');self.app.redraw()
        self.assertTrue(self.app._texture_photos)
    def test_load_companion_into_existing_base_and_clear(self):
        self.assertTrue(self.app.load_file(FIXTURES/'indycar.3do'))
        before=self.app.model
        ref=next(iter(before.vertices))
        old=before.vertices[ref].xyz
        before.set_vertex(ref,(old[0]+5,*old[1:]))
        self.assertTrue(self.app.load_car_appearance(FIXTURES/'ind96.3do'))
        self.assertIs(self.app.model,before)
        self.assertEqual(self.app.model.vertices[ref].xyz[0],old[0]+5)
        self.app.clear_car_appearance()
        self.assertIsNone(self.app.appearance)
        self.assertEqual(self.app.model.vertices[ref].xyz[0],old[0]+5)
    def test_open_new_base_clears_appearance(self):
        self.app.load_file(FIXTURES/'ind96.3do')
        self.app.load_file(FIXTURES/'roadcar.3do')
        self.assertIsNone(self.app.appearance)
        self.assertEqual(self.app.model.path.name,'roadcar.3do')
    def test_mismatch_dialog_can_keep_custom_loaded_model(self):
        self.app.load_file(FIXTURES/'roadcar.3do')
        with patch('icr2_3do_cad.messagebox.askyesnocancel',return_value=False):
            self.assertTrue(self.app.load_car_appearance(FIXTURES/'ind96.3do'))
        self.assertEqual(self.app.model.path.name,'roadcar.3do')
        self.assertEqual(self.app.appearance.texture_name,'ind96')

if __name__=='__main__':unittest.main()
