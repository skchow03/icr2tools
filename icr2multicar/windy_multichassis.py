"""WINDY101 multi-chassis geometry unlock for ICR2Runtime v0.13.

Read-only by default. The `on` and `run` actions change game memory;
`off` restores the exact runtime-tracked patch. This script changes the
shared chassis geometry pointer only, not per-car wheel or tire pointers.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time
from typing import Any

# Find the matching ICR2Runtime client in the repository or beside the script.
_THIS_DIR = Path(__file__).resolve().parent
_RUNTIME_DIRS = (_THIS_DIR.parent / "icr2runtime", _THIS_DIR,
                 _THIS_DIR / "icr2runtime")
for _runtime_dir in _RUNTIME_DIRS:
    if (_runtime_dir / "icr2_client.py").is_file() and \
            (_runtime_dir / "runtime_launcher.py").is_file():
        sys.path.insert(0, str(_runtime_dir))
        break

from icr2_client import ICR2Client, RuntimeErrorResponse
from runtime_launcher import ensure_runtime, RuntimeCapabilityError, RuntimeStartupError

CHASSIS_ADDRESS = 0x0045B719  # WINDY101 Ghidra virtual address, not a file offset
ORIGINAL = bytes.fromhex("89 02")  # mov [edx], eax
REPLACEMENT = bytes.fromhex("90 90")  # nop; nop
RUNTIME_VERSION = "0.13"


class WrapperError(RuntimeError):
    pass


def runtime_binary_path(choice: str | None) -> str | None:
    if choice:
        path = Path(choice).expanduser().resolve()
        if not path.is_file():
            raise WrapperError(f"Runtime EXE does not exist: {path}")
        return str(path)
    # Prefer built executables over a copy in the source directory.
    for directory in _RUNTIME_DIRS:
        for filename in ("build/Debug/icr2runtime.exe", "build/Release/icr2runtime.exe",
                         "icr2runtime.exe"):
            candidate = directory / filename
            if candidate.is_file():
                return str(candidate)
    return None


def get_client(action: str, explicit_exe: str | None) -> ICR2Client:
    if action in ("on", "run"):
        # An explicit write operation may launch the shared service with code writes.
        # Existing read-only instances are never promoted.
        return ensure_runtime(runtime_path=runtime_binary_path(explicit_exe),
                              enable_code_writes=True)
    # Read-only checks and restoration require an existing service; restoration
    # must use the service holding the original-byte snapshot.
    client = ICR2Client()
    try:
        if not client.ping():
            raise WrapperError("ICR2Runtime did not respond to PING")
    except OSError as exc:
        raise WrapperError("No running ICR2Runtime v0.13 service. Start it first; "
                           "for writes use --enable-code-writes.") from exc
    return client


def select_game(client: ICR2Client, pid: int | None) -> Any:
    games = [g for g in client.list_games() if g.version == "WINDY101"]
    if pid is not None:
        games = [g for g in games if g.pid == pid]
    if not games:
        client.refresh()
        games = [g for g in client.list_games() if g.version == "WINDY101"]
        if pid is not None:
            games = [g for g in games if g.pid == pid]
    if not games:
        raise WrapperError("No matching WINDY101 process detected. Start WINDY "
                           "and make sure ICR2Runtime recognizes it.")
    if len(games) > 1:
        raise WrapperError("More than one WINDY101 instance detected; choose --pid. "
                           + ", ".join(str(g.pid) for g in games))
    return games[0]


def require_runtime(client: ICR2Client) -> dict[str, str]:
    status = client.status()
    if status.get("version") != RUNTIME_VERSION:
        raise WrapperError(f"Expected ICR2Runtime v{RUNTIME_VERSION}, got "
                           + repr(status.get("version")) + ". Rebuild the C++ "
                           "runtime and use its matching Python client.")
    return status


def owned_record(client: ICR2Client, pid: int):
    patches = [p for p in client.list_patches()
               if p[0] == pid and p[1] == CHASSIS_ADDRESS]
    if len(patches) > 1:
        raise WrapperError("Multiple patch entries at the same address")
    if not patches:
        return None
    record = patches[0]
    if (record[2] != "CODE" or record[3] != ORIGINAL or
            record[4] != REPLACEMENT):
        raise WrapperError("ICR2Runtime tracks a DIFFERENT patch at 0x0045B719; "
                           "refusing to alter it")
    return record


def inspect(client: ICR2Client, pid: int):
    observed = client.read_bytes(pid, CHASSIS_ADDRESS, 2)
    tracked = owned_record(client, pid)
    if observed == ORIGINAL and tracked is None:
        return "READY", observed
    if observed == REPLACEMENT and tracked is not None:
        return "APPLIED_TRACKED", observed
    if observed == REPLACEMENT and tracked is None:
        return "APPLIED_UNTRACKED", observed
    if observed == ORIGINAL and tracked is not None:
        return "TRACKING_MISMATCH", observed
    return "UNKNOWN_BYTES", observed


def report(client: ICR2Client, pid: int) -> str:
    state, observed = inspect(client, pid)
    print(f"WINDY101 PID {pid}; address 0x{CHASSIS_ADDRESS:08X}; "
          f"bytes: {observed.hex(' ').upper()}; state: {state}")
    if state == "APPLIED_UNTRACKED":
        print("WARNING: The instruction is patched, but the active runtime has "
              "no restore record. Another injector or runtime instance may "
              "have modified it. No write will be attempted.")
    if state == "UNKNOWN_BYTES":
        print("WARNING: Unexpected instruction bytes. A different build or "
              "third-party code patch may be present. No write will be attempted.")
    return state


def apply(client: ICR2Client, pid: int) -> bool:
    state, _ = inspect(client, pid)
    if state == "APPLIED_TRACKED":
        print("Already enabled and tracked by this ICR2Runtime instance.")
        return False
    if state != "READY":
        raise WrapperError(f"Refusing patch: {state} (expected untouched 89 02)")
    if "PATCH_CODE" not in client.capabilities():
        raise WrapperError("Runtime is read-only for executable code. Restart "
                           "v0.13 with --enable-code-writes; an existing "
                           "read-only service cannot be upgraded.")
    client.patch_code(pid, CHASSIS_ADDRESS, ORIGINAL, REPLACEMENT)
    if inspect(client, pid)[0] != "APPLIED_TRACKED":
        raise WrapperError("Patch was submitted but verification failed; "
                           "use 'check' and 'off' to inspect/restore")
    print("Per-car chassis geometry enabled. The runtime tracks the "
          "two-byte patch and retains its restore snapshot.")
    return True


def restore(client: ICR2Client, pid: int) -> bool:
    state, _ = inspect(client, pid)
    if state == "READY":
        print("No chassis patch is active.")
        return False
    if state != "APPLIED_TRACKED":
        raise WrapperError(f"Cannot restore safely: {state}. "
                           "Only an exact runtime-tracked patch can be restored.")
    client.restore(pid, CHASSIS_ADDRESS)
    if inspect(client, pid)[0] != "READY":
        raise WrapperError("RESTORE returned but original bytes were not verified")
    print("Restored original 89 02 instruction and released runtime patch record.")
    return True


def run(client: ICR2Client, pid: int):
    # Do not 'adopt' a patch that belongs to another command or process.
    if inspect(client, pid)[0] == "APPLIED_TRACKED":
        raise WrapperError("Patch is already active. Use 'off' to restore it "
                           "before starting a managed wrapper session.")
    applied = False
    try:
        applied = apply(client, pid)
        print("Wrapper active. Leave this terminal open while driving; "
              "press Ctrl+C to restore. Wheel/tire hook is NOT installed.")
        while True:
            time.sleep(1.0)
            # Do not continue driving silently if the tracked patch has changed.
            if inspect(client, pid)[0] != "APPLIED_TRACKED":
                raise WrapperError("Game stopped, patch changed or runtime "
                                   "tracking was lost. Do not auto-repatch.")
    except KeyboardInterrupt:
        print("\nStopping wrapper...")
    finally:
        # Even if verification after PATCHCODE raises, PATCHCODE itself may
        # already have succeeded. Since run() began from READY, an exact
        # tracked patch created during this attempt should be restored.
        try:
            state, _ = inspect(client, pid)
            if state == "APPLIED_TRACKED":
                restore(client, pid)
            elif applied:
                raise WrapperError("Previously applied patch is no longer "
                                   "safely restorable: " + state)
        except Exception as exc:
            print("RESTORE FAILED OR COULD NOT BE VERIFIED: " + str(exc),
                  file=sys.stderr)
            print("Keep the game and runtime open; inspect with 'check', "
                  "then try 'off'.", file=sys.stderr)
            raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=f"WINDY101 multi-chassis geometry patch via ICR2Runtime v{RUNTIME_VERSION}")
    parser.add_argument("action", nargs="?", default="check",
                        choices=("check", "on", "off", "run"),
                        help="check=read-only; on=enable; off=restore; "
                             "run=enable and hold until Ctrl+C")
    parser.add_argument("--pid", type=int,
                        help="Select WINDY101 process if more than one is running")
    parser.add_argument("--runtime-exe", metavar="PATH",
                        help=f"Path to ICR2Runtime v{RUNTIME_VERSION} executable "
                             "if automatic startup is needed")
    args = parser.parse_args(argv)
    try:
        client = get_client(args.action, args.runtime_exe)
        status = require_runtime(client)
        game = select_game(client, args.pid)
        print(f"ICR2Runtime {status['version']}; code writes: "
              f"{'ENABLED' if 'PATCH_CODE' in client.capabilities() else 'disabled'}")
        if args.action == "check":
            report(client, game.pid)
        elif args.action == "on":
            apply(client, game.pid)
        elif args.action == "off":
            restore(client, game.pid)
        elif args.action == "run":
            run(client, game.pid)
        return 0
    except (WrapperError, RuntimeCapabilityError, RuntimeStartupError,
            RuntimeErrorResponse, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
