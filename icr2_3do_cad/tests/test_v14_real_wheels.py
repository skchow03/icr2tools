"""Regression tests using the actual user-supplied ICR2 wheel assets."""
import tempfile
import unittest
from pathlib import Path
from shutil import copyfile

from three_do import Model
from dynamic_scene import ExternalResolver, gather_faces
from texture_preview import load_mip

ROOT=Path(__file__).resolve().parents[1]
FIX=ROOT/'fixtures'

class RealWheelTests(unittest.TestCase):
    def test_material_wrapper_root_zero_negative_external_pointer(self):
        for wrapper_name, wheel_name in [('sfront','fwheel'),('srear','rwheel')]:
            wrapper=Model(FIX/f'{wrapper_name}.3do')
            self.assertEqual(wrapper.root_offset,0)
            self.assertEqual(wrapper.external_names,[wheel_name])
            self.assertEqual(wrapper.children[0],[-1])
            events=[]
            wrapper.switched_polygons(0,(0,100000,10000),'original',events=events)
            self.assertEqual(events,[('external',-1,'wheel1')])
            faces, errors=gather_faces(wrapper,0,(0,100000,10000),'original',ExternalResolver())
            self.assertFalse(errors,errors)
            self.assertGreater(len(faces),0)
            self.assertEqual({f.source.path.name for f in faces},{f'{wheel_name}.3do'})
            self.assertEqual({f.texture_override for f in faces},{'wheel1'})

    def test_variable_length_res_three_branches(self):
        for name in ('fwheel','rwheel'):
            m=Model(FIX/f'{name}.3do')
            self.assertEqual(len(m.polygons),34)
            self.assertEqual(len(m.switches),1)
            self.assertEqual([t for t,_ in next(iter(m.switches.values())).branches],
                             [280000,113750,0])
            for distance in (0,125000,400000):
                faces,errors=gather_faces(m,distance,(100000,-100000,20000),'original',ExternalResolver())
                self.assertFalse(errors)
                self.assertTrue(faces)
            self.assertEqual(m.build_modified_bytes()[0],(FIX/f'{name}.3do').read_bytes())

    def test_all_four_real_wheels_and_original_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)
            for name in ('roadcar.3do','indycar.3do','sfront.3do','srear.3do',
                         'fwheel.3do','rwheel.3do','wheel1.mip'):
                copyfile(FIX/name,dest/name)
            original={p.name:p.read_bytes() for p in dest.iterdir() if p.is_file()}
            for main in ('roadcar.3do','indycar.3do'):
                model=Model(dest/main)
                for d in (0,130000,400000):
                    faces,errors=gather_faces(model,d,(0,-100000,20000),'original',ExternalResolver())
                    self.assertEqual({e for e in errors if e not in (8700,8440)},set(),errors)
                    seen={f.placement for f in faces if f.placement is not None}
                    self.assertEqual(seen,{5268,5300,5332,5364})
                    self.assertTrue(all(f.texture_override=='wheel1' for f in faces if f.placement is not None))
                self.assertEqual(model.build_modified_bytes()[0],original[main])
            self.assertEqual({p.name:p.read_bytes() for p in dest.iterdir() if p.is_file()},original)

    def test_actual_mip_paletted(self):
        mip=load_mip(FIX/'wheel1.mip')
        self.assertEqual((mip[0].width,mip[0].height),(256,128))
        self.assertEqual(len(mip),8)

if __name__=='__main__':
    unittest.main()
