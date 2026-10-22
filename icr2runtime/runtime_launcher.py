"""Start or reuse the shared ICR2Runtime v0.13 service on Windows.

The service remains independent of this Python application's lifetime.
Importing this module does not load Windows-only ctypes code, which also
allows the launcher logic to be unit-tested on non-Windows platforms.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Optional


class RuntimeCapabilityError(RuntimeError):
    """A shared runtime exists but was not started with the requested write flags."""


class RuntimeStartupError(RuntimeError):
    """The bundled/shared runtime could not be started or contacted."""


def _cache_bundled_binary(executable: Path) -> Path:
    """Copy PyInstaller's temporary EXE to a durable, versioned per-user path.

    The digest isolates updates and prevents the temporary-file cleanup at
    application exit from removing the executable of a live service.
    """
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()[:24]
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    target_dir = base / "ICR2Tools" / "ICR2Runtime" / digest
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "icr2runtime.exe"
    if target.is_file():
        return target

    with tempfile.NamedTemporaryFile(prefix="icr2-", suffix=".exe",
                                     dir=target_dir, delete=False) as tmp:
        temporary = Path(tmp.name)
        with executable.open("rb") as source:
            shutil.copyfileobj(source, tmp)
    try:
        os.replace(temporary, target)
    except PermissionError:
        # Another simultaneous launcher may have installed/started this
        # identical digest while we copied it; never overwrite a running EXE.
        if not target.is_file():
            raise
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _runtime_executable(runtime_path: Optional[os.PathLike | str] = None) -> Path:
    if runtime_path is not None:
        exe = Path(runtime_path).resolve()
    elif hasattr(sys, "_MEIPASS"):
        exe = Path(sys._MEIPASS) / "icr2runtime.exe"
    elif getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve().parent / "icr2runtime.exe"
    else:
        exe = Path(__file__).resolve().parent / "icr2runtime.exe"
    if not exe.is_file():
        raise FileNotFoundError(
            f"ICR2Runtime executable not found: {exe}. "
            "Bundle it with --add-binary or pass runtime_path."
        )
    if hasattr(sys, "_MEIPASS") and exe.parent.resolve() == Path(sys._MEIPASS).resolve():
        return _cache_bundled_binary(exe)
    return exe


def _check_capabilities(client, data_writes: bool, code_writes: bool) -> None:
    available = client.capabilities()
    requested = set()
    if data_writes:
        requested.add("PATCH_DATA")
    if code_writes:
        requested.add("PATCH_CODE")
    missing = requested - available
    if missing:
        raise RuntimeCapabilityError(
            "Shared ICR2Runtime is running without required capabilities: "
            + ", ".join(sorted(missing))
            + ". It will not be restarted or upgraded automatically. "
              "Close clients and restart the service with the appropriate "
              "explicit --enable-*-writes flags."
        )


def ensure_runtime(*, runtime_path: Optional[os.PathLike | str] = None,
                   enable_data_writes: bool = False,
                   enable_code_writes: bool = False,
                   idle_timeout: int = 60,
                   startup_timeout: float = 12.0):
    """Return an ICR2Client connected to one shared service.

    Reuse a running service regardless of the local bundled EXE. If absent,
    launch with read-only defaults; write flags require explicit caller opt-in.
    Idle shutdown is a service feature, not a request to kill the child from
    this application. Keep an ICR2Session open while continuously using it.
    """
    if not 0 <= idle_timeout <= 3600:
        raise ValueError("idle_timeout must be 0..3600 seconds")
    if startup_timeout <= 0:
        raise ValueError("startup_timeout must be positive")

    from icr2_client import ICR2Client

    client = ICR2Client()
    try:
        if client.ping():
            _check_capabilities(client, enable_data_writes, enable_code_writes)
            return client
    except OSError:
        pass

    executable = _runtime_executable(runtime_path)
    command = [str(executable), "--idle-timeout", str(idle_timeout)]
    if enable_data_writes:
        command.append("--enable-data-writes")
    if enable_code_writes:
        command.append("--enable-code-writes")

    # The C++ named mutex serializes concurrent launchers. A process that
    # loses that race exits normally; both launchers poll the same pipe.
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    # PyInstaller sets the Windows DLL search path to its _MEI extraction
    # directory. Child processes inherit it, potentially loading VC runtime
    # DLLs from _MEI and keeping that directory locked after we exit.
    # Temporarily restore the standard search order for the external service.
    bundled_dir = getattr(sys, "_MEIPASS", None)
    dll_api = None
    if sys.platform == "win32" and bundled_dir:
        import ctypes
        dll_api = ctypes.windll.kernel32.SetDllDirectoryW
        if not dll_api(None):
            raise RuntimeStartupError("Could not reset DLL search path before launching ICR2Runtime")
    try:
        # Keep the shared child independent of a PyInstaller onefile
        # extraction directory that the parent must delete on exit.
        child = subprocess.Popen(command, cwd=str(executable.parent),
                                 creationflags=flags,
                                 stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL,
                                 close_fds=True)
    except OSError as exc:
        raise RuntimeStartupError(f"Could not launch {executable}: {exc}") from exc
    finally:
        if dll_api is not None:
            # Restore the bundled application's own DLL lookup behavior.
            if not dll_api(str(bundled_dir)):
                raise RuntimeStartupError("Could not restore bundled DLL search path")

    deadline = time.monotonic() + startup_timeout
    while time.monotonic() < deadline:
        try:
            if client.ping():
                _check_capabilities(client, enable_data_writes, enable_code_writes)
                return client
        except OSError:
            pass
        time.sleep(0.1)

    code = child.poll()
    raise RuntimeStartupError(
        f"ICR2Runtime v0.13 pipe did not become available within {startup_timeout}s "
        f"(launcher exit code: {code}). Check that this is a v0.13 binary "
        "and start it manually to inspect errors."
    )
