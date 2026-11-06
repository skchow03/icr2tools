"""Workspace selection must not infer a file type from generic 3DO geometry."""
import unittest
from pathlib import Path

from workspaces import (
    WORKSPACE_MODES, suggest_workspace, workspace_scene_summary,
    resolve_lod_distance,
)


class WorkspaceModesTests(unittest.TestCase):
    def test_three_workspaces_are_stable(self):
        self.assertEqual(WORKSPACE_MODES, ("car", "track", "object"))

    def test_simplified_lod_selector_preserves_renderer_contract(self):
        self.assertEqual(resolve_lod_distance("auto", 12345), "auto")
        self.assertEqual(resolve_lod_distance("manual", 12345), 12345)
        self.assertIsNone(resolve_lod_distance("all", 12345))
        with self.assertRaises(ValueError):
            resolve_lod_distance("invalid", 12345)

    def test_known_car_shapes_and_appearance_wrappers(self):
        self.assertEqual(suggest_workspace("ROADCAR.3DO", {}), "car")
        self.assertEqual(suggest_workspace("panoz.3do", {}), "car")
        self.assertEqual(suggest_workspace(
            "cit74.3do", {"appearance_geometry": "indycar"}), "car")
        self.assertEqual(suggest_workspace(
            "custom.3do", {"recolor_pairs": 12}), "car")

    def test_known_tracks(self):
        self.assertEqual(suggest_workspace(Path("RENO.3D"), {}), "track")
        self.assertEqual(suggest_workspace("track.3do", {}), "track")
        self.assertEqual(suggest_workspace("track_miami.3d", {}), "track")
        self.assertEqual(suggest_workspace("putnam_track.3d", {}), "track")

    def test_track_structure_overrides_ambiguous_filename(self):
        self.assertEqual(suggest_workspace("PUTNAM.3D", {"track_section_lists": 76}), "track")
        self.assertEqual(suggest_workspace(None, {"track_section_lists": 1}), "track")
        self.assertEqual(suggest_workspace("PUTNAM.3D", {}), None)

    def test_ambiguous_names_remain_user_selected(self):
        for name in ("grandstand.3do", "wasp.3d", "testmodel.3d"):
            with self.subTest(name=name):
                self.assertIsNone(suggest_workspace(name, {}))
        self.assertIsNone(suggest_workspace(None, {}))

    def test_mode_specific_scene_summaries(self):
        stats = {
            "model_vertices": 300, "model_planes": 52,
            "model_polygons": 75, "mips": 2, "external_objects": 4,
            "dynamic_instances": 7, "switches": 3,
            "external_warnings": ("lost_wheel.3do",),
        }
        self.assertIn("7 external instances", workspace_scene_summary("track", stats))
        self.assertIn("1 unresolved references", workspace_scene_summary("track", stats))
        self.assertIn("2 named MIPs", workspace_scene_summary("object", stats))
        self.assertIn("4 DYNAMIC references", workspace_scene_summary("object", stats))
        with self.assertRaises(ValueError):
            workspace_scene_summary("car", stats)


if __name__ == "__main__":
    unittest.main()
