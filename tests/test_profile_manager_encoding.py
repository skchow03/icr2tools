import os
import tempfile
import unittest

try:
    from icr2timing.ui.profile_manager import ProfileManager, Profile
except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard
    if exc.name == "PyQt5":
        ProfileManager = None  # type: ignore[assignment]
        Profile = None  # type: ignore[assignment]
    else:
        raise


class ProfileManagerEncodingTests(unittest.TestCase):
    @unittest.skipIf(ProfileManager is None, "PyQt5 not available")
    def test_save_and_load_with_non_ascii_characters(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "profiles.ini")

            manager = ProfileManager(cfg_path)
            profile = Profile(
                name="Tést",
                columns=["Nómbré", "Velocidad", "ΔRápido"],
                custom_fields=[("Velocidad máxima", 3)],
            )

            manager.save(profile)

            reloaded = ProfileManager(cfg_path).load("Tést")

            self.assertIsNotNone(reloaded)
            assert reloaded is not None  # for typing
            self.assertIn("Nómbré", reloaded.columns)
            self.assertIn("ΔRápido", reloaded.columns)
            self.assertEqual(reloaded.custom_fields, [("Velocidad máxima", 3)])


if __name__ == "__main__":
    unittest.main()
