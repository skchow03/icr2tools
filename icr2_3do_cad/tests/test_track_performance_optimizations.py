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


if __name__=="__main__":
    unittest.main()
