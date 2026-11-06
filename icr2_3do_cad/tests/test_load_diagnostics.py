"""Consolidated model-load diagnostics without a Qt/OpenGL dependency."""
import unittest

from load_diagnostics import (
    LoadIssue, collect_load_issues, format_load_log,
)


class LoadDiagnosticsTests(unittest.TestCase):
    def test_clean_model_has_no_reported_issues(self):
        self.assertEqual(collect_load_issues({}), ())
        report = format_load_log("track.3d", ())
        self.assertIn("track.3d", report)
        self.assertIn("No load errors or asset warnings", report)
        self.assertNotIn("1 issue", report)

    def test_all_asset_diagnostics_included_without_truncation(self):
        stats = {
            "external_warnings": (
                "wheel: referenced wheel.3do / wheel.3d not found",
                "broken.3do: invalid model",
                "wheel: referenced wheel.3do / wheel.3d not found",
            ),
            "missing_textures": tuple(f"wall{i}.mip" for i in range(12)),
            "texture_errors": ("wall.3mip: invalid dimensions",),
            "pmp_warnings": ("helmet.pmp: missing",),
            "palette_warning": "SUNNY.PCX: corrupt palette",
            "skybox_error": "HORIZ.3D: invalid polygon",
            "skybox_missing_mips": ("sky01.mip", "sky02.mip"),
            "skybox_texture_errors": ("sky03.mip: invalid mip",),
            "trk_error": "track.trk: invalid centerline",
        }
        issues = collect_load_issues(stats)
        # 2 unique external, 12 missing MIPs, 1 MIP error, 1 PMP,
        # 1 palette, 1 skybox, 2 sky MIPs, 1 sky MIP error, 1 TRK.
        self.assertEqual(len(issues), 22)
        self.assertEqual(
            sum(issue.category == "Referenced objects" for issue in issues), 2)
        self.assertEqual(
            sum(issue.category == "Missing MIP textures" for issue in issues), 12)
        report = format_load_log("/folder/track.3do", issues)
        self.assertIn("22 issues reported", report)
        self.assertIn("wall0.mip", report)
        self.assertIn("wall11.mip", report)
        self.assertIn("Referenced objects (2)", report)
        self.assertIn("Missing MIP textures (12)", report)
        self.assertIn("Skybox MIP textures (3)", report)
        self.assertIn("track.trk: invalid centerline", report)
        self.assertEqual(report.count("referenced wheel.3do"), 1)

    def test_absent_optional_assets_not_reported_as_failures(self):
        stats = {
            "skybox_path": "",
            "skybox_missing_mips": (),
            "skybox_error": "",
            "trk_path": "",
            "trk_error": "",
            "external_warnings": (),
            "missing_textures": (),
        }
        self.assertFalse(collect_load_issues(stats))

    def test_failed_model_load_remains_reportable(self):
        issues = (LoadIssue("Model load", "FormatError: truncated LIST"),)
        report = format_load_log("broken.3d", issues)
        self.assertIn("1 issue reported", report)
        self.assertIn("Model load (1)", report)
        self.assertIn("FormatError: truncated LIST", report)


if __name__ == "__main__":
    unittest.main()
