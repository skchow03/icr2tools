"""Regressions using actual supplied Papyrus helmet PMP and 3DO files."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from three_do import Model
from dynamic_scene import ExternalResolver,RenderSprite,gather_faces
from pmp_preview import load_pmp, PMPError
from icr2_3do_cad import read_pcx_palette

class PMPSpriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.palette=read_pcx_palette(ROOT/'gamepal.pcx')
        cls.resolver=ExternalResolver(ROOT/'fixtures')

    def test_all_16_supplied_helmets_decode_and_have_alpha(self):
        paths=list((ROOT/'fixtures').glob('helm*.pmp'))
        self.assertEqual(len(paths),16)
        for path in paths:
            sprite=load_pmp(path,self.palette)
            self.assertEqual(sprite.auxiliary,30)
            self.assertTrue(20<=sprite.rgba.width<=80,path.name)
            self.assertTrue(20<=sprite.rgba.height<=80,path.name)
            self.assertEqual(sprite.rgba.getpixel((0,0))[3],0)
            self.assertGreater(sprite.rgba.getbbox()[2],10)

    def test_real_helmet_bsp_selects_one_view(self):
        for name in ('helmet.3do','helmetp.3do'):
            model=Model(ROOT/'fixtures'/name)
            self.assertEqual(len(model.pmp_sprites),8)
            self.assertEqual(len(model.polygons),0)
            seen=set()
            for i,j in ((10000,0),(10000,10000),(0,10000),(-10000,10000),
                        (-10000,0),(-10000,-10000),(0,-10000),(10000,-10000)):
                events=[]
                model.switched_polygons(0,(i,j,1500),'original',events=events)
                sprites=[model.pmp_sprites[ref].name for typ,ref,*_ in events if typ=='pmp']
                self.assertEqual(len(sprites),1,(name,(i,j),sprites))
                seen.update(sprites)
            self.assertGreaterEqual(len(seen),6)

    def test_pmp_children_in_parent_transform_and_painter_order(self):
        model=Model(ROOT/'fixtures'/'indycar.3do')
        for cam in ((0,-100000,50000),(100000,30000,50000),(-100000,30000,50000)):
            faces,failures=gather_faces(model,0,cam,'original',self.resolver)
            self.assertFalse(failures)
            sprites=[f for f in faces if isinstance(f,RenderSprite)]
            self.assertEqual(len(sprites),1)
            sprite=sprites[0]
            self.assertEqual(sprite.placement,8440)
            self.assertEqual(sprite.source.path.name,'helmet.3do')
            self.assertEqual(sprite.transform.apply((0,0,0)),(10761.,0.,4035.))
            self.assertTrue(any(f.placement in (5268,5300,5332,5364)
                                for f in faces))

    def test_external_helmet_files_preserved_after_transform_edit(self):
        model=Model(ROOT/'fixtures'/'indycar.3do')
        originals={path.name:path.read_bytes() for path in (ROOT/'fixtures').glob('helm*.pmp')}
        original3do=(ROOT/'fixtures'/'helmet.3do').read_bytes()
        before=model.build_modified_bytes()[0]
        model.set_dynamic(8440,(12000,0,5000),model.dynamics[8440].angles)
        changed=model.build_modified_bytes()[0]
        self.assertNotEqual(before,changed)
        self.assertEqual(len(changed),len(before))
        self.assertEqual((ROOT/'fixtures'/'helmet.3do').read_bytes(),original3do)
        self.assertTrue(all((ROOT/'fixtures'/n).read_bytes()==b for n,b in originals.items()))

    def test_malformed_pmp_fails(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as td:
            p=Path(td)/'malformed.pmp'
            p.write_bytes(b'not a pmp')
            with self.assertRaises(PMPError):load_pmp(p,self.palette)

class PMPDesktopTest(unittest.TestCase):
    def test_real_helmet_shows_as_canvas_sprite(self):
        from icr2_3do_cad import Editor
        try:app=Editor()
        except Exception as e:
            self.skipTest('Tk desktop unavailable: '+str(e))
        try:
            app.geometry('1400x950+0+0')
            app.update()
            self.assertTrue(app.load_file(ROOT/'fixtures'/'indycar.3do'))
            app.external_resolver.choose_directory(ROOT/'fixtures')
            app.redraw()
            self.assertTrue(app.canvas.find_withtag('pmp'))
            self.assertFalse(app._dynamic_failures)
            app.show_textures.set(False)
            app.redraw()
            self.assertFalse(app.canvas.find_withtag('pmp'))
        finally:app.destroy()

if __name__=='__main__':unittest.main()
