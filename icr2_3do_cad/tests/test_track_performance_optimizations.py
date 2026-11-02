"""Large-track load and preview optimizations must preserve model semantics."""
import unittest
from pathlib import Path

from three_do import Model, plane_distance, polygon_triplet

HERE=Path(__file__).resolve().parents[1]/"fixtures"


class PlaneAssociationRegressionTests(unittest.TestCase):
    @staticmethod
    def legacy_plane_associations(model):
        """Reference: original uncached association algorithm, independent of optimization."""
        expected={}
        for plane in model.planes.values():
            a,b,c,d=plane.equation
            if (a,b,c)==(0,0,0):
                expected[plane.offset]=((),None,None,"unmatched")
                continue
            candidates=[]
            for poly in model.polygons.values():
                if len(poly.unique_refs)<3:
                    continue
                if polygon_triplet(poly,model.vertices,original=True) is None:
                    continue
                pts=[model.vertices[r].original for r in poly.unique_refs]
                if all(plane_distance(plane.equation,p)<=0.5 for p in pts):
                    candidates.append(poly.offset)
            local=model._descendant_poly_distances(plane.offset)
            eligible=[p for p in candidates if p in local]
            if not eligible:
                anchor=None
                distance=None
                confidence="global-only" if candidates else "unmatched"
            else:
                eligible.sort(key=lambda p:(local[p],p))
                distance=local[eligible[0]]
                closest=[p for p in eligible if local[p]==distance]
                anchor=eligible[0] if len(closest)==1 else None
                confidence="local" if len(closest)==1 else "ambiguous"
            expected[plane.offset]=(tuple(candidates),anchor,distance,confidence)
        return expected

    def test_optimized_associations_match_legacy_on_real_models(self):
        for name in ("roadcar","indycar","panoz"):
            with self.subTest(name=name):
                model=Model(HERE/f"{name}.3do")
                original=self.legacy_plane_associations(model)
                for offset,plane in model.planes.items():
                    actual=(tuple(plane.candidates),plane.anchor,plane.distance,
                            plane.confidence)
                    self.assertEqual(actual,original[offset],f"{name} plane {offset}")
                self.assertEqual(model.build_modified_bytes()[0],model.raw)

    def test_preserve_safe_plane_rebuild_after_move(self):
        model=Model(HERE/"roadcar.3do")
        ref=next(iter(model.vertices))
        old=model.vertices[ref].xyz
        model.set_vertex(ref,(old[0]+13,old[1],old[2]))
        modified,report=model.build_modified_bytes()
        self.assertEqual(len(modified),len(model.raw))
        self.assertGreaterEqual(report.updated_planes,0)


class LargeViewportMarkerTests(unittest.TestCase):
    def setUp(self):
        from icr2_3do_cad import Editor
        self.app=Editor()
        self.app.geometry("1100x750")
        self.app.update_idletasks()
        self.assertTrue(self.app.load_file(HERE/"roadcar.3do"))
        self.app.update_idletasks()
        self.app.show_points.set(True)

    def tearDown(self):
        self.app.destroy()

    def test_dense_markers_are_one_photoimage_but_all_vertices_remain_pickable(self):
        from icr2_3do_cad import TEXTURE_AVAILABLE
        if not TEXTURE_AVAILABLE:
            self.skipTest("Pillow/texture preview unavailable")
        app=self.app
        app._point_raster_threshold=1  # Exercise track path using roadcar fixture.
        app.redraw()
        self.assertEqual(len(app.canvas.find_withtag("dot")),1)
        self.assertTrue(app._texture_photos)
        self.assertGreater(len(app.active_vertices),30)
        ref=next(iter(app.active_vertices))
        x,y,_=app._project(app.model.vertices[ref].xyz)
        # Pick logic tests all vertices, not only rendered Tk canvas items.
        class Click:
            pass
        event=Click()
        event.x=x;event.y=y
        app.start_pick(event)
        self.assertIsNotNone(app.selected)
        self.assertIn(app.selected,app.active_vertices)

    def test_small_models_retain_editable_per_vertex_tk_dots(self):
        app=self.app
        app._point_raster_threshold=10**9
        app.redraw()
        self.assertGreater(len(app.canvas.find_withtag("dot")),1)

    def test_vertex_list_batch_preserves_order_and_labels(self):
        app=self.app
        app._populate_vertex_list()
        self.assertEqual(app.listbox.size(),len(app.vertex_order))
        for row in (0,25,len(app.vertex_order)-1):
            self.assertEqual(app.listbox.get(row),
                             app._vertex_list_text(app.vertex_order[row]))

    def test_basis_changes_with_camera_pose_and_is_reused(self):
        from icr2_3do_cad import _view_basis
        app=self.app
        basis=app._basis()
        self.assertIs(basis,app._basis())
        app.azimuth+=0.25
        changed=app._basis()
        self.assertNotEqual(changed,basis)
        self.assertIs(changed,_view_basis(app.azimuth,app.elevation))


if __name__=="__main__":
    unittest.main()
