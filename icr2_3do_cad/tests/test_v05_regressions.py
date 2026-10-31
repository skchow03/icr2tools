"""v0.5 regressions: BSP-only edits, reversed presentation Y and backup writes."""
import math
import tempfile
import unittest
from pathlib import Path
from icr2_3do_cad import Editor, write_validated_3do
from three_do import Model, FormatError, NAMES

FIXTURES=Path(__file__).resolve().parents[1]/'fixtures'


class V05Tests(unittest.TestCase):
    def test_flip_without_xyz_changes_affects_rebuilt_preview(self):
        m=Model(FIXTURES/'roadcar.3do')
        source,_,_=m.switched_polygons(None,(100000,0,30000),'original')
        preview_original,_,_=m.switched_polygons(None,(100000,0,30000),'rebuilt')
        self.assertEqual(source,preview_original)
        self.assertIn(7896,source)
        m.flip_plane(9124,7896)
        self.assertFalse(m.modified_vertices)
        self.assertEqual(m.effective_plane(9124),tuple(-n for n in m.planes[9124].equation))
        after,_,_=m.switched_polygons(None,(100000,0,30000),'rebuilt')
        self.assertNotEqual(after,source)
        self.assertNotIn(7896,after)
        same_original,_,_=m.switched_polygons(None,(100000,0,30000),'original')
        self.assertEqual(same_original,source)
        # Save and reopen: edited preview must agree with stored coefficients.
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'flipped.3do'
            out.write_bytes(m.build_modified_bytes()[0])
            checked=Model(out)
            loaded,_,_=checked.switched_polygons(None,(100000,0,30000),'original')
            self.assertEqual(after,loaded)
        m.flip_plane(9124,7896)
        self.assertEqual(m.switched_polygons(None,(100000,0,30000),'rebuilt')[0],source)

    def test_manual_plane_without_xyz_edits_affects_preview(self):
        m=Model(FIXTURES/'roadcar.3do')
        old,_stat,_=m.switched_polygons(None,(-100000,0,30000),'original')
        refs=m.polygons[7896].unique_refs
        m.set_plane_edit(9124,7896,'manual',(refs[0],refs[2],refs[1]))
        self.assertFalse(m.modified_vertices)
        rebuilt,_stat,_=m.switched_polygons(None,(-100000,0,30000),'rebuilt')
        # Explicit coefficients and preview use the same saved equation.
        out,report=m.build_modified_bytes()
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'new.3do';path.write_bytes(out)
            check=Model(path)
            self.assertEqual(rebuilt,check.switched_polygons(None,(-100000,0,30000),'original')[0])
        self.assertEqual(old,m.switched_polygons(None,(-100000,0,30000),'original')[0])

    def test_y_projection_is_reversed_but_coordinates_are_not(self):
        class Simple:
            azimuth=math.radians(35)
            elevation=math.radians(25)
        right,up,toward=Editor._basis(Simple())
        self.assertGreater(right[1],0, '+Y must now point toward the right on screen')
        self.assertGreater(up[1],0, '+Y must now point upward on screen')
        self.assertAlmostEqual(sum(r*u for r,u in zip(right,up)),0)
        self.assertAlmostEqual(sum(r*t for r,t in zip(right,toward)),0)
        m=Model(FIXTURES/'roadcar.3do')
        self.assertEqual(m.build_modified_bytes()[0],m.raw)

    def test_backup_overwrites_existing_and_tracks_immediate_prior_file(self):
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'roadcar.3do'
            target.write_bytes((FIXTURES/'roadcar.3do').read_bytes())
            original=target.read_bytes()
            bak=target.with_suffix('.3do.bak')
            bak.write_bytes(b'OLD BACKUP')
            m=Model(target)
            p=7896;pl=9124
            m.flip_plane(pl,p)
            changed=m.build_modified_bytes()[0]
            checked=write_validated_3do(target,changed,
                        expected_vertices=len(m.vertices),
                        expected_polygons=len(m.polygons),backup=True)
            self.assertEqual(bak.read_bytes(),original)
            self.assertEqual(target.read_bytes(),changed)
            self.assertEqual(checked.raw,changed)
            checked.flip_plane(pl,p)
            second=checked.build_modified_bytes()[0]
            write_validated_3do(target,second,
                        expected_vertices=len(m.vertices),
                        expected_polygons=len(m.polygons),backup=True)
            self.assertEqual(bak.read_bytes(),changed)
            self.assertEqual(target.read_bytes(),second)

    def test_invalid_output_does_not_replace_target_or_backup(self):
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'original.3do'
            target.write_bytes((FIXTURES/'roadcar.3do').read_bytes())
            original=target.read_bytes()
            bak=target.with_suffix('.3do.bak')
            bak.write_bytes(b'prior')
            with self.assertRaises(FormatError):
                write_validated_3do(target,b'invalid 3do',
                                    expected_vertices=325,expected_polygons=124,
                                    backup=True)
            self.assertEqual(target.read_bytes(),original)
            self.assertEqual(bak.read_bytes(),b'prior')

if __name__=='__main__': unittest.main()
