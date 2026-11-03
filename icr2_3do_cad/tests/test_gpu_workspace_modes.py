"""Workspace selection must not infer a file type from generic 3DO geometry."""
import unittest
from pathlib import Path

from gpu_viewer.workspaces import (
    WORKSPACE_MODES, suggest_workspace, workspace_scene_summary,
)


class WorkspaceModesTests(unittest.TestCase):
    def test_three_workspaces_are_stable(self):
        self.assertEqual(WORKSPACE_MODES, ("car", "track", "object"))

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
