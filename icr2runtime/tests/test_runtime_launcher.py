"""ICR2Runtime v0.13 launcher contract tests (no ICR2 game required)."""
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime_launcher


class LauncherTests(unittest.TestCase):
    def _client_module(self, client):
        return mock.patch.dict(sys.modules, {"icr2_client": types.SimpleNamespace(
            ICR2Client=lambda: client)})

    def test_reuses_running_service_without_loading_exe(self):
        client = mock.Mock()
        client.ping.return_value = True
        client.capabilities.return_value = {"READ", "BULK"}
        with self._client_module(client), mock.patch.object(
            runtime_launcher, "_runtime_executable"
        ) as resolve, mock.patch.object(runtime_launcher.subprocess, "Popen") as popen:
            self.assertIs(runtime_launcher.ensure_runtime(), client)
            resolve.assert_not_called()
            popen.assert_not_called()

    def test_write_requirement_does_not_escalate_running_service(self):
        client = mock.Mock()
        client.ping.return_value = True
        client.capabilities.return_value = {"READ"}
        with self._client_module(client), mock.patch.object(
            runtime_launcher.subprocess, "Popen"
        ) as popen:
            with self.assertRaises(runtime_launcher.RuntimeCapabilityError):
                runtime_launcher.ensure_runtime(enable_data_writes=True)
            popen.assert_not_called()

    def test_starts_read_only_after_missing_pipe(self):
        client = mock.Mock()
        client.ping.side_effect = [OSError("pipe missing"), True]
        client.capabilities.return_value = {"READ"}
        with self._client_module(client), mock.patch.object(
            runtime_launcher, "_runtime_executable", return_value=Path("icr2runtime.exe")
        ), mock.patch.object(runtime_launcher.subprocess, "Popen") as popen:
            self.assertIs(runtime_launcher.ensure_runtime(idle_timeout=90), client)
            self.assertEqual(popen.call_args.args[0],
                             ["icr2runtime.exe", "--idle-timeout", "90"])
            self.assertEqual(popen.call_args.kwargs["cwd"], ".")

    def test_launch_race_reuses_other_winner(self):
        client = mock.Mock()
        client.ping.side_effect = [OSError("missing"), OSError("starting"), True]
        client.capabilities.return_value = {"READ"}
        with self._client_module(client), mock.patch.object(
            runtime_launcher, "_runtime_executable", return_value=Path("icr2runtime.exe")
        ), mock.patch.object(runtime_launcher.subprocess, "Popen") as popen, mock.patch.object(
            runtime_launcher.time, "sleep"
        ):
            self.assertIs(runtime_launcher.ensure_runtime(), client)
            popen.assert_called_once()

    def test_explicit_write_launch_flags(self):
        client = mock.Mock()
        client.ping.side_effect = [OSError("missing"), True]
        client.capabilities.return_value = {"READ", "PATCH_DATA", "PATCH_CODE"}
        with self._client_module(client), mock.patch.object(
            runtime_launcher, "_runtime_executable", return_value=Path("icr2runtime.exe")
        ), mock.patch.object(runtime_launcher.subprocess, "Popen") as popen:
            runtime_launcher.ensure_runtime(enable_data_writes=True,
                                            enable_code_writes=True)
            self.assertIn("--enable-data-writes", popen.call_args.args[0])
            self.assertIn("--enable-code-writes", popen.call_args.args[0])

    def test_bundled_exe_cached_outside_pyinstaller_temp(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            bundle = root / "bundle"
            bundle.mkdir()
            (bundle / "icr2runtime.exe").write_bytes(b"test binary")
            with mock.patch.object(sys, "_MEIPASS", str(bundle), create=True), \
                    mock.patch.dict(os.environ, {"LOCALAPPDATA": str(root / "local")}):
                first = runtime_launcher._runtime_executable()
                self.assertNotEqual(first.parent, bundle)
                self.assertEqual(first.read_bytes(), b"test binary")
                self.assertEqual(runtime_launcher._runtime_executable(), first)


@unittest.skipUnless(sys.platform == "win32" and os.environ.get("ICR2RUNTIME_EXE"),
                     "Windows-only integration needs ICR2RUNTIME_EXE")
class ServiceWindowsTests(unittest.TestCase):
    """Build the C++ executable first; these checks need no running game."""

    def setUp(self):
        import subprocess
        from icr2_client import ICR2Client
        self.subprocess = subprocess
        self.client = ICR2Client()
        self.process = None

    def tearDown(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except self.subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=8)

    def _start(self, timeout=0):
        self.process = self.subprocess.Popen(
            [os.environ["ICR2RUNTIME_EXE"], "--idle-timeout", str(timeout)],
            stdout=self.subprocess.DEVNULL, stderr=self.subprocess.DEVNULL)
        import time
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            try:
                if self.client.ping():
                    return
            except OSError:
                pass
            time.sleep(0.2)
        self.fail("C++ service failed to expose the v0.13 pipe")

    def test_single_instance_and_capability_reporting(self):
        self._start()
        self.assertEqual(self.client.status()["version"], "0.13")
        caps = self.client.capabilities()
        self.assertIn("LIFECYCLE_IDLE", caps)
        self.assertNotIn("PATCH_DATA", caps)
        self.assertNotIn("PATCH_GUEST_CODE", caps)
        other = self.subprocess.Popen(
            [os.environ["ICR2RUNTIME_EXE"]],
            stdout=self.subprocess.DEVNULL, stderr=self.subprocess.DEVNULL)
        self.assertEqual(other.wait(timeout=10), 0)
        self.assertIsNone(self.process.poll())
        self.assertTrue(self.client.ping())

    def test_code_write_flag_reports_guest_capability(self):
        import subprocess
        import time
        self.process = subprocess.Popen(
            [os.environ["ICR2RUNTIME_EXE"], "--enable-code-writes"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            try:
                if self.client.ping():
                    break
            except OSError:
                pass
            time.sleep(0.2)
        else:
            self.fail("v0.13 service did not start")
        caps = self.client.capabilities()
        self.assertIn("PATCH_CODE", caps)
        self.assertIn("PATCH_GUEST_CODE", caps)
        self.assertNotIn("PATCH_DATA", caps)

    def test_idle_exit_respects_active_session(self):
        from icr2_client import ICR2Session
        import time
        self._start(timeout=2)
        with ICR2Session() as session:
            time.sleep(3)
            self.assertEqual(session.request("PING"), "OK\tPONG\n")
            self.assertIsNone(self.process.poll())
        self.assertEqual(self.process.wait(timeout=10), 0)


if __name__ == "__main__":
    unittest.main()

