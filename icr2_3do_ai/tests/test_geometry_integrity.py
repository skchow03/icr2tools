"""Phase 1: source-generator surface integrity and polygon regression tests."""
from __future__ import annotations

import copy
import unittest

from icr2_3do_ai.parametric import RecipeError, generate_source
from icr2_3do_ai.stage2 import validate_source


def recipe(*ops, policy="warn"):
    return {"schema": "icr2.n3.recipe.v1",
            "coordinate_scale": 6000,
            "surface_checks": policy,
            "operations": list(ops)}


def sheet(name, outline, *, axis="z", at=0):
    return {"type":"polygon", "name":name, "axis":axis, "at":at,
            "outline":outline, "color":40}


class GeometryIntegrityTests(unittest.TestCase):
    def test_caps_backward_compatible_and_independently_selectable(self):
        base = {"type":"loft", "name":"bonnet", "axis":"x",
                "sections":[
                    {"at":0,"width":2,"height":2,"center":[0,1]},
                    {"at":3,"width":2,"height":2,"center":[0,1]},
                ],"color":158}
        for caps, count, first, last in (
            (True,10,True,True),
            (False,8,False,False),
            ({"start":False,"end":True},9,False,True),
            ({"start":True,"end":False},9,True,False),
        ):
            with self.subTest(caps=caps):
                op=copy.deepcopy(base)
                op["caps"]=caps
                source,manifest=generate_source(recipe(op))
                model,details=validate_source(source)
                self.assertEqual(details["polygons"],count)
                self.assertEqual(manifest["polygon_count"],count)
                first_x=0
                last_x=18000
                cap_locations=[
                    {model.vertices[r].xyz[0] for r in poly.unique_refs}
                    for poly in model.polygons.values()
                ]
                self.assertEqual(sum(x=={first_x} for x in cap_locations),int(first))
                self.assertEqual(sum(x=={last_x} for x in cap_locations),int(last))
        extrude={"type":"extrude","name":"upright","axis":"z",
                 "from":0,"to":2,
                 "outline":[[0,0],[2,0],[2,2],[0,2]],
                 "caps":{"start":False,"end":True}}
        _,manifest=generate_source(recipe(extrude))
        self.assertEqual(manifest["polygon_count"],9)

    def test_native_convex_flat_fin_is_single_ungated_poly(self):
        # Deliberately resembles the V29 arched tail fin (concave not needed).
        outline=[[0,0],[0,4],[1,5.5],[2,6],[3,5.5],[4,4],[4,0]]
        src,manifest=generate_source(recipe(sheet("flat_fin",outline,axis="y")))
        model,details=validate_source(src)
        self.assertEqual(details["polygons"],1)
        self.assertEqual(manifest["polygon_count"],1)
        self.assertEqual(len(model.polygons),1)
        poly=next(iter(model.polygons.values()))
        self.assertEqual(len(poly.unique_refs),7)
        self.assertTrue(all(model.vertices[r].xyz[1]==0
                            for r in poly.unique_refs))
        self.assertNotIn("FACE ",src)
        self.assertEqual(manifest["surface_checks"]["counts"],{})

    def test_concave_polygon_is_triangulated_without_hidden_thickness(self):
        outline=[[0,0],[3,0],[3,1],[1,1],[1,3],[0,3]]
        src,manifest=generate_source(recipe(sheet("flat_L",outline)))
        model,details=validate_source(src)
        self.assertEqual(details["polygons"],4)
        self.assertEqual(manifest["polygon_count"],4)
        self.assertEqual(len(model.vertices),6)
        self.assertTrue(all(len(p.unique_refs)==3
                            for p in model.polygons.values()))
        self.assertTrue(all(model.vertices[r].xyz[2]==0
                            for p in model.polygons.values()
                            for r in p.unique_refs))
        src2,_=generate_source(recipe(sheet("flat_L",list(reversed(outline)))))
        self.assertEqual(src,src2)

    def test_invalid_polygon_and_cap_configuration_rejected(self):
        invalid = [
            sheet("bowtie",[[0,0],[3,3],[0,3],[3,0]]),
            sheet("tiny",[[0,0],[0.00001,0],[3,0],[3,3],[0,3]]),
            sheet("touching",[[0,0],[3,0],[3,3],[2,0],[0,3]]),
            {**sheet("flat",[[0,0],[2,0],[0,2]]),"caps":True},
            {**sheet("flat",[[0,0],[2,0],[0,2]]),"axis":"t"},
        ]
        for op in invalid:
            with self.subTest(op=op["name"]), self.assertRaises(RecipeError):
                generate_source(recipe(op))
        loft={"type":"loft","name":"body","axis":"x",
              "sections":[{"at":0,"width":2,"height":1},
                          {"at":1,"width":2,"height":1}],
              "caps":{"start":True}}
        with self.assertRaises(RecipeError):
            generate_source(recipe(loft))
        with self.assertRaises(RecipeError):
            generate_source(recipe(sheet("good",[[0,0],[2,0],[0,2]]),
                                   policy="unexpected"))

    def test_exact_duplicate_faces_warn_and_can_fail_strictly(self):
        square=[[0,0],[2,0],[2,2],[0,2]]
        data=recipe(sheet("roof",square),sheet("second_roof",square))
        _,manifest=generate_source(data)
        self.assertIn("DUPLICATE_SURFACE",
                      manifest["surface_checks"]["counts"])
        self.assertEqual(manifest["surface_checks"]["policy"],"warn")
        data["surface_checks"]="error"
        with self.assertRaisesRegex(RecipeError,"DUPLICATE_SURFACE"):
            generate_source(data)
        data["surface_checks"]="off"
        _,manifest=generate_source(data)
        self.assertEqual(manifest["surface_checks"]["diagnostics"],[])

    def test_coplanar_overlap_detected_but_shared_edge_not_flagged(self):
        a=sheet("roof",[[0,0],[2,0],[2,2],[0,2]])
        crossing=sheet("raised",[[1,1],[3,1],[3,3],[1,3]])
        _,manifest=generate_source(recipe(a,crossing))
        self.assertIn("COPLANAR_OVERLAP",
                      manifest["surface_checks"]["counts"])
        touching=sheet("neighbor",[[2,0],[4,0],[4,2],[2,2]])
        _,report=generate_source(recipe(a,touching))
        self.assertEqual(report["surface_checks"]["diagnostics"],[])

    def test_overlapping_bonnet_and_cowl_lofts_are_reported(self):
        # Regression for the real Wasp modeling mistake: a second hull
        # occupies the same exterior volume instead of extending one loft.
        bonnet={"type":"loft","name":"bonnet","axis":"x","color":159,
                "caps":False,"sections":[
                    {"at":0,"width":2,"height":1,"center":[0,.5]},
                    {"at":4,"width":2,"height":1,"center":[0,.5]},
                ]}
        cowl={"type":"loft","name":"cowl","axis":"x","color":158,
              "caps":False,"sections":[
                  {"at":2,"width":2,"height":1,"center":[0,1]},
                  {"at":4,"width":2,"height":1,"center":[0,1]},
              ]}
        _,m=generate_source(recipe(bonnet,cowl))
        collisions=m["surface_checks"]["counts"]
        self.assertTrue(
            {"COPLANAR_OVERLAP","INTERSECTING_SURFACES"}.intersection(collisions),
            collisions
        )
        with self.assertRaises(RecipeError):
            generate_source(recipe(bonnet,cowl,policy="error"))

    def test_cross_plane_intersection_warned_and_separated_sheets_clear(self):
        horizontal=sheet("bonnet",[[0,0],[3,0],[3,3],[0,3]])
        vertical=sheet("cowl",[[1,-1],[2,-1],[2,1],[1,1]],
                       axis="x",at=1)
        _,manifest=generate_source(recipe(horizontal,vertical))
        self.assertIn("INTERSECTING_SURFACES",
                      manifest["surface_checks"]["counts"])
        away=sheet("upper",[[0,0],[3,0],[3,3],[0,3]],at=2)
        _,manifest=generate_source(recipe(horizontal,away))
        self.assertEqual(manifest["surface_checks"]["diagnostics"],[])

    def test_existing_recipe_schema_defaults_unchanged(self):
        plain={"schema":"icr2.n3.recipe.v1","coordinate_scale":6000,
               "operations":[{"type":"extrude","name":"box","axis":"z",
                              "outline":[[0,0],[2,0],[2,2],[0,2]],
                              "from":0,"to":1,"color":33}]}
        source,manifest=generate_source(plain)
        self.assertEqual(manifest["polygon_count"],10)
        self.assertEqual(manifest["surface_checks"]["policy"],"warn")
        self.assertIn("box_p0009: POLY <33>",source)


if __name__=="__main__":
    unittest.main()
