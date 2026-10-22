"""WINDY101 multi-car geometry and per-car wheel/tire selection.

The `check` action is read-only. The `run` action uses ICR2Runtime
for guarded, tracked instruction patches and manages a separate executable
page for the per-car wheel/tire routine. Ctrl+C attempts to restore both.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from pathlib import Path
import struct
import sys
import time
from typing import Any

# Locate the matching ICR2Runtime client in the repository or beside this file.
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
    if action == "run":
        # An explicit write operation may launch the shared service with code writes.
        # Existing read-only instances are never promoted.
        return ensure_runtime(runtime_path=runtime_binary_path(explicit_exe),
                              enable_code_writes=True)
    # A read-only check connects to an existing runtime without starting one.
    client = ICR2Client()
    try:
        if not client.ping():
            raise WrapperError("ICR2Runtime did not respond to PING")
    except OSError as exc:
        raise WrapperError(f"No running ICR2Runtime v{RUNTIME_VERSION} service. "
                           "Start it first; for writes use --enable-code-writes.") from exc
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


def _chassis_owned_record(client: ICR2Client, pid: int):
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


def _chassis_inspect(client: ICR2Client, pid: int):
    observed = client.read_bytes(pid, CHASSIS_ADDRESS, 2)
    tracked = _chassis_owned_record(client, pid)
    if observed == ORIGINAL and tracked is None:
        return "READY", observed
    if observed == REPLACEMENT and tracked is not None:
        return "APPLIED_TRACKED", observed
    if observed == REPLACEMENT and tracked is None:
        return "APPLIED_UNTRACKED", observed
    if observed == ORIGINAL and tracked is not None:
        return "TRACKING_MISMATCH", observed
    return "UNKNOWN_BYTES", observed


def _chassis_report(client: ICR2Client, pid: int) -> str:
    state, observed = _chassis_inspect(client, pid)
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


def _chassis_apply(client: ICR2Client, pid: int) -> bool:
    state, _ = _chassis_inspect(client, pid)
    if state == "APPLIED_TRACKED":
        print("Already enabled and tracked by this ICR2Runtime instance.")
        return False
    if state != "READY":
        raise WrapperError(f"Refusing patch: {state} (expected untouched 89 02)")
    if "PATCH_CODE" not in client.capabilities():
        raise WrapperError("Runtime is read-only for executable code. Restart "
                           f"v{RUNTIME_VERSION} with --enable-code-writes; an existing "
                           "read-only service cannot be upgraded.")
    client.patch_code(pid, CHASSIS_ADDRESS, ORIGINAL, REPLACEMENT)
    if _chassis_inspect(client, pid)[0] != "APPLIED_TRACKED":
        raise WrapperError("Patch was submitted but verification failed; "
                           "inspect the runtime-tracked patch and restore it before retrying")
    print("Per-car chassis geometry enabled. The runtime tracks the "
          "two-byte patch and retains its restore snapshot.")
    return True


def _chassis_restore(client: ICR2Client, pid: int) -> bool:
    state, _ = _chassis_inspect(client, pid)
    if state == "READY":
        print("No chassis patch is active.")
        return False
    if state != "APPLIED_TRACKED":
        raise WrapperError(f"Cannot restore safely: {state}. "
                           "Only an exact runtime-tracked patch can be restored.")
    client.restore(pid, CHASSIS_ADDRESS)
    if _chassis_inspect(client, pid)[0] != "READY":
        raise WrapperError("RESTORE returned but original bytes were not verified")
    print("Restored original 89 02 instruction and released runtime patch record.")
    return True


WHEEL_SITE = 0x004607C0
WHEEL_ORIGINAL = bytes.fromhex("E8 34 ED FF FF")
WINDY_IMAGE_BASE = 0x00400000
WHEEL_FUNCTION = 0x004A6FB0   # call "WINDY.EXE"+A6FB0
TIRE_FUNCTION = 0x0045F4F9   # call "WINDY.EXE"+5F4F9
WHEEL_NODE_SLOTS = 0x00514760
TIRE_APPEARANCE_SLOTS = 0x00514780
GEOMETRY_SLOT_TABLE = 0x00513660
MEM_COMMIT, MEM_RESERVE, MEM_RELEASE = 0x1000, 0x2000, 0x8000
PAGE_READWRITE, PAGE_EXECUTE_READ = 0x04, 0x20
PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000  # Required for WaitForSingleObject(process)

# x86 wheel/tire selection routine with address and relative-branch fixups.
# Marker bytes 0x11, 0x22 and 0x33 stand in for CALL/CALL/JMP displacements.
# Absolute addresses are relocated to WINDY's loaded image base.
CODE_TEMPLATE = bytes.fromhex(
    "9c 60 8b 06 8b 40 74 83 f8 20 77 38"
    "8b 3c 85 60 36 51 00 85 ff 74 2d 31 db"
    "53 57 e8 11 11 11 11 83 c4 08 85 c0 74 1d"
    "89 04 9d 60 47 51 00 8b 10 85 d2 74 10"
    "8d 52 1c 89 14 9d 80 47 51 00 43 83 fb 04 7c d5"
    "61 9d e8 22 22 22 22 e9 33 33 33 33"
)
# Offset of four-byte argument fields inside CODE_TEMPLATE.
RELOCATIONS = {
    0x0f: GEOMETRY_SLOT_TABLE,
    0x1c: WHEEL_FUNCTION,     # rel32 CALL after push edi
    0x2a: WHEEL_NODE_SLOTS,
    0x3a: TIRE_APPEARANCE_SLOTS,
    0x47: TIRE_FUNCTION,      # original CALL from replaced code
    0x4c: WHEEL_SITE + 5,    # return to next WINDY instruction
}
REL32 = {0x1c, 0x47, 0x4c}
PAGE_SIZE = 4096


def _win32():
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.VirtualAllocEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                   wintypes.DWORD, wintypes.DWORD]
    k32.VirtualAllocEx.restype = ctypes.c_void_p
    k32.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    k32.WriteProcessMemory.restype = wintypes.BOOL
    k32.VirtualProtectEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                     wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    k32.VirtualProtectEx.restype = wintypes.BOOL
    k32.FlushInstructionCache.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t]
    k32.FlushInstructionCache.restype = wintypes.BOOL
    k32.VirtualFreeEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                  wintypes.DWORD]
    k32.VirtualFreeEx.restype = wintypes.BOOL
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.WaitForSingleObject.restype = wintypes.DWORD
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL
    return k32


def _checked(result, operation):
    if not result:
        raise OSError(ctypes.get_last_error(), operation)
    return result


def _rel32(place_after_instruction: int, destination: int) -> bytes:
    return struct.pack('<I', (destination - place_after_instruction) & 0xFFFFFFFF)


def build_cave(base: int, image_base: int = WINDY_IMAGE_BASE) -> bytes:
    """Relocate the x86 routine's absolute pointers and relative branches."""
    if not (0 <= base < 2**32 and 0 <= image_base < 2**32):
        raise WrapperError("Expected 32-bit addresses for WINDY x86 code cave")
    shift = image_base - WINDY_IMAGE_BASE
    blob = bytearray(CODE_TEMPLATE)
    for offset, native_target in RELOCATIONS.items():
        target = native_target + shift
        if not 0 <= target < 2**32:
            raise WrapperError("Relocated WINDY target outside 32-bit space")
        if offset in REL32:
            blob[offset:offset+4] = _rel32(base + offset + 4, target)
        else:
            blob[offset:offset+4] = struct.pack('<I', target)
    return bytes(blob)


def wheel_jump(cave_addr: int, wheel_site: int = WHEEL_SITE) -> bytes:
    return b'\xE9' + _rel32(wheel_site + 5, cave_addr)


class RemoteCave:
    def __init__(self, pid: int):
        self.k32 = _win32()
        permissions = (PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE |
                       PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE)
        self.process = _checked(self.k32.OpenProcess(permissions, False, pid),
                                "OpenProcess(WINDY)")
        self.address = 0

    def install(self, client, pid: int, image_base: int):
        raw = self.k32.VirtualAllocEx(self.process, None, PAGE_SIZE,
                                     MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE)
        if not raw:
            raise ctypes.WinError(ctypes.get_last_error())
        self.address = int(raw)
        if self.address >= 2**32:
            raise WrapperError("WINDY is x86, but allocation exceeds 32-bit address space")
        blob = build_cave(self.address, image_base)
        source = ctypes.create_string_buffer(blob)
        written = ctypes.c_size_t()
        _checked(self.k32.WriteProcessMemory(self.process, ctypes.c_void_p(self.address),
                                              source, len(blob), ctypes.byref(written)),
                 "WriteProcessMemory(code cave)")
        if written.value != len(blob):
            raise WrapperError("Partial write of wheel/tire code cave")
        # Readback through ICR2Runtime; WINDY uses identity Ghidra/host addressing.
        if client.read_bytes(pid, self.address, len(blob)) != blob:
            raise WrapperError("Code cave readback does not match injected code")
        old_protection = wintypes.DWORD()
        _checked(self.k32.VirtualProtectEx(self.process, ctypes.c_void_p(self.address),
                                           PAGE_SIZE, PAGE_EXECUTE_READ,
                                           ctypes.byref(old_protection)),
                 "VirtualProtectEx(code cave RX)")
        _checked(self.k32.FlushInstructionCache(self.process, ctypes.c_void_p(self.address),
                                                 len(blob)), "FlushInstructionCache(code cave)")
        return blob

    def has_exited(self) -> bool:
        """Check the original process handle, not a potentially reused PID."""
        result = self.k32.WaitForSingleObject(self.process, 0)
        if result == 0:  # WAIT_OBJECT_0
            return True
        if result == 0x102:  # WAIT_TIMEOUT
            return False
        raise ctypes.WinError(ctypes.get_last_error())

    def release(self):
        if not self.address:
            return
        _checked(self.k32.VirtualFreeEx(self.process, ctypes.c_void_p(self.address),
                                        0, MEM_RELEASE), "VirtualFreeEx(code cave)")
        self.address = 0

    def close(self):
        if self.process:
            self.k32.CloseHandle(self.process)
            self.process = None


def wheel_state(client, pid: int):
    observed = client.read_bytes(pid, WHEEL_SITE, 5)
    patches = [p for p in client.list_patches() if p[0] == pid and p[1] == WHEEL_SITE]
    if observed == WHEEL_ORIGINAL and not patches:
        return 'READY', observed
    if patches:
        return 'TRACKED_OTHER_PATCH', observed
    return ('UNTRACKED_JUMP' if observed[:1] == b'\xE9' else 'UNKNOWN_BYTES'), observed


def validate_image(client, game):
    if game.version != 'WINDY101':
        raise WrapperError('This hook supports WINDY101 only')
    # Absolute data pointers in the assembly require genuine PE image base,
    # not merely a guessed DOSBox memory translation. WINDY is expected at 0x400000.
    if game.translation_base != 0 or game.host_module_base != WINDY_IMAGE_BASE:
        raise WrapperError(
            f'Unexpected WINDY address layout: translation=0x{game.translation_base:X}, '
            f'host PE base=0x{game.host_module_base:X}. Do not inject on an unverified layout.')
    # Require the exact original instructions at the hook site.
    expected = client.read_bytes(game.pid, WHEEL_SITE, len(WHEEL_ORIGINAL))
    if expected != WHEEL_ORIGINAL:
        raise WrapperError(f'Wheel/tire hook site is not original: {expected.hex(" ")}')


def report(client, game):
    print(f'WINDY101 PID {game.pid}; runtime v{client.status()["version"]}')
    _chassis_report(client, game.pid)
    state, raw = wheel_state(client, game.pid)
    print(f'Wheel/tire site 0x{WHEEL_SITE:08X}: {raw.hex(" ").upper()}; state: {state}')
    return state


def run(client, game):
    if 'PATCH_CODE' not in client.capabilities():
        raise WrapperError(f'Runtime code writes disabled. Restart v{RUNTIME_VERSION} with --enable-code-writes')
    validate_image(client, game)
    if _chassis_inspect(client, game.pid)[0] != 'READY':
        raise WrapperError('Chassis patch is already active or modified. Restore the original '
                           'instruction before starting this tool.')
    if wheel_state(client, game.pid)[0] != 'READY':
        raise WrapperError('Wheel/tire hook already installed or modified. '
                           'Remove any conflicting injector before retrying.')
    cave = RemoteCave(game.pid)
    chassis_attempted = False
    wheel_expected = None
    try:
        cave.install(client, game.pid, game.host_module_base)
        wheel_expected = wheel_jump(cave.address)
        # Only five original bytes are changed. The return address is +5.
        client.patch_code(game.pid, WHEEL_SITE, WHEEL_ORIGINAL, wheel_expected)
        if client.read_bytes(game.pid, WHEEL_SITE, 5) != wheel_expected:
            raise WrapperError('Wheel hook patch did not verify')
        chassis_attempted = True
        _chassis_apply(client, game.pid)
        print(f'Wheel/tire hook installed at 0x{WHEEL_SITE:08X}; '
              f'x86 cave at 0x{cave.address:08X} ({len(CODE_TEMPLATE)} bytes).')
        print('Chassis + wheel/tire hook active. Press Ctrl+C to restore before '
              'closing WINDY. Closing WINDY first is also detected.')
        while True:
            time.sleep(1)
            if cave.has_exited():
                print('WINDY exited; ending Multi-Car session.')
                break
            try:
                if client.read_bytes(game.pid, WHEEL_SITE, 5) != wheel_expected:
                    raise WrapperError('Wheel hook changed while WINDY is running')
                if _chassis_inspect(client, game.pid)[0] != 'APPLIED_TRACKED':
                    raise WrapperError('Chassis override changed while WINDY is running')
            except (RuntimeErrorResponse, OSError):
                if cave.has_exited():
                    print('WINDY exited during status check; ending session.')
                    break
                raise
    except KeyboardInterrupt:
        print('\nStopping multi-car hooks...')
    finally:
        # A terminated process has no executable detour or allocated code cave.
        # Do not attempt runtime RESTORE on a vanished game.
        if cave.has_exited():
            print('WINDY has exited. Windows released its memory and injected '
                  'code cave; no instruction restoration is needed.')
            cave.close()
        else:
            # Never free executable code while the detour can still jump to it.
            # A failed pipe response can occur after a successful code write.
            # Check the live detour and runtime record before freeing its target.
            safe_to_release = False
            errors = []
            if cave.address:
                try:
                    observed = client.read_bytes(game.pid, WHEEL_SITE, 5)
                    matches = [p for p in client.list_patches()
                               if p[0] == game.pid and p[1] == WHEEL_SITE]
                    if wheel_expected is not None and observed == wheel_expected:
                        if (len(matches) != 1 or matches[0][2] != 'CODE' or
                                matches[0][3] != WHEEL_ORIGINAL or
                                matches[0][4] != wheel_expected):
                            raise WrapperError('Wheel hook is live but not tracked as expected')
                        client.restore(game.pid, WHEEL_SITE)
                        if client.read_bytes(game.pid, WHEEL_SITE, 5) != WHEEL_ORIGINAL:
                            raise WrapperError('Wheel detour restoration not confirmed')
                        print('Wheel/tire JMP restored.')
                        safe_to_release = True
                    elif observed == WHEEL_ORIGINAL and not matches:
                        safe_to_release = True
                    else:
                        raise WrapperError('Wheel site is modified or tracked unexpectedly; '
                                                   'keeping cave allocated to avoid a dangling JMP')
                except Exception as exc:
                    errors.append(f'wheel restore: {exc}')
            if chassis_attempted:
                try:
                    state, _ = _chassis_inspect(client, game.pid)
                    if state == 'APPLIED_TRACKED':
                        _chassis_restore(client, game.pid)
                    elif state != 'READY':
                        raise WrapperError('Chassis patch not safely restorable: ' + state)
                except Exception as exc:
                    errors.append(f'chassis restore: {exc}')
            if safe_to_release:
                try:
                    # Detach before release. This delay reduces (but cannot eliminate)
                    # the risk that a render thread is still executing the cave.
                    time.sleep(0.5)
                    cave.release()
                    print('Detached code cave released.')
                except Exception as exc:
                    errors.append(f'code cave release: {exc}')
            # Recheck the process before reporting cleanup failure: WINDY
            # may have exited during the restoration RPCs or the delay.
            exited_during_cleanup = cave.has_exited()
            if not safe_to_release and not exited_during_cleanup:
                print('WARNING: code cave NOT released; wheel detour may still reference it.',
                      file=sys.stderr)
            cave.close()
            if exited_during_cleanup:
                print('WINDY exited during cleanup; Windows released its memory.')
            elif errors:
                raise WrapperError('Cleanup incomplete while WINDY remains alive; '
                                   + ' | '.join(errors))
            else:
                print('Both hooks restored. You can exit WINDY normally.')


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=f'WINDY101 multi-car model support (ICR2Runtime v{RUNTIME_VERSION})')
    parser.add_argument('action', nargs='?', default='check', choices=('check', 'run'))
    parser.add_argument('--pid', type=int)
    parser.add_argument('--runtime-exe', help=f'Path to compiled ICR2Runtime v{RUNTIME_VERSION}, if startup is needed')
    args = parser.parse_args(argv)
    try:
        client = get_client(args.action, args.runtime_exe)
        require_runtime(client)
        game = select_game(client, args.pid)
        if args.action == 'check':
            report(client, game)
        else:
            run(client, game)
        return 0
    except (WrapperError, RuntimeCapabilityError, RuntimeStartupError,
            RuntimeErrorResponse, OSError, ValueError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
