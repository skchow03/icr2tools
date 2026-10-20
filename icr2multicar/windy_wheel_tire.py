"""WINDY101 per-car wheel/tire and chassis hook via ICR2Runtime v0.13.

The `check` action is read-only. The `run` action installs guarded code
patches and manages a private executable page in WINDY for the per-car wheel
and tire selection routine. Keep `run` active until restoration completes.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import struct
import sys
import time

# Reuse chassis patch verification and the matching runtime client.
import windy_multichassis as chassis
from icr2_client import RuntimeErrorResponse
from runtime_launcher import RuntimeCapabilityError, RuntimeStartupError

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
        raise chassis.WrapperError("Expected 32-bit addresses for WINDY x86 code cave")
    shift = image_base - WINDY_IMAGE_BASE
    blob = bytearray(CODE_TEMPLATE)
    for offset, native_target in RELOCATIONS.items():
        target = native_target + shift
        if not 0 <= target < 2**32:
            raise chassis.WrapperError("Relocated WINDY target outside 32-bit space")
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
                       PROCESS_QUERY_LIMITED_INFORMATION)
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
            raise chassis.WrapperError("WINDY is x86, but allocation exceeds 32-bit address space")
        blob = build_cave(self.address, image_base)
        source = ctypes.create_string_buffer(blob)
        written = ctypes.c_size_t()
        _checked(self.k32.WriteProcessMemory(self.process, ctypes.c_void_p(self.address),
                                              source, len(blob), ctypes.byref(written)),
                 "WriteProcessMemory(code cave)")
        if written.value != len(blob):
            raise chassis.WrapperError("Partial write of wheel/tire code cave")
        # Readback through ICR2Runtime; WINDY uses identity Ghidra/host addressing.
        if client.read_bytes(pid, self.address, len(blob)) != blob:
            raise chassis.WrapperError("Code cave readback does not match injected code")
        old_protection = wintypes.DWORD()
        _checked(self.k32.VirtualProtectEx(self.process, ctypes.c_void_p(self.address),
                                           PAGE_SIZE, PAGE_EXECUTE_READ,
                                           ctypes.byref(old_protection)),
                 "VirtualProtectEx(code cave RX)")
        _checked(self.k32.FlushInstructionCache(self.process, ctypes.c_void_p(self.address),
                                                 len(blob)), "FlushInstructionCache(code cave)")
        return blob

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
        raise chassis.WrapperError('This hook supports WINDY101 only')
    # Absolute data pointers in the assembly require genuine PE image base,
    # not merely a guessed DOSBox memory translation. WINDY is expected at 0x400000.
    if game.translation_base != 0 or game.host_module_base != WINDY_IMAGE_BASE:
        raise chassis.WrapperError(
            f'Unexpected WINDY address layout: translation=0x{game.translation_base:X}, '
            f'host PE base=0x{game.host_module_base:X}. Do not inject on an unverified layout.')
    # Require the exact original instructions at the hook site.
    expected = client.read_bytes(game.pid, WHEEL_SITE, len(WHEEL_ORIGINAL))
    if expected != WHEEL_ORIGINAL:
        raise chassis.WrapperError(f'Wheel/tire hook site is not original: {expected.hex(" ")}')


def report(client, game):
    print(f'WINDY101 PID {game.pid}; runtime v{client.status()["version"]}')
    chassis.report(client, game.pid)
    state, raw = wheel_state(client, game.pid)
    print(f'Wheel/tire site 0x{WHEEL_SITE:08X}: {raw.hex(" ").upper()}; state: {state}')
    return state


def run(client, game):
    if 'PATCH_CODE' not in client.capabilities():
        raise chassis.WrapperError('Runtime code writes disabled. Restart v0.13 with --enable-code-writes')
    validate_image(client, game)
    if chassis.inspect(client, game.pid)[0] != 'READY':
        raise chassis.WrapperError('Chassis patch already active/modified. Stop the previous '
                                   'wrapper with Ctrl+C and restore 89 02 first.')
    if wheel_state(client, game.pid)[0] != 'READY':
        raise chassis.WrapperError('Wheel/tire hook already installed or modified. '
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
            raise chassis.WrapperError('Wheel hook patch did not verify')
        chassis_attempted = True
        chassis.apply(client, game.pid)
        print(f'Wheel/tire hook installed at 0x{WHEEL_SITE:08X}; '
              f'x86 cave at 0x{cave.address:08X} ({len(CODE_TEMPLATE)} bytes).')
        print('Chassis + wheel/tire hook active. Press Ctrl+C to restore both. '
              'Do not close WINDY or the runtime during this session.')
        while True:
            time.sleep(1)
            if client.read_bytes(game.pid, WHEEL_SITE, 5) != wheel_expected:
                raise chassis.WrapperError('Wheel hook changed or WINDY disappeared')
            if chassis.inspect(client, game.pid)[0] != 'APPLIED_TRACKED':
                raise chassis.WrapperError('Chassis override changed or WINDY disappeared')
    except KeyboardInterrupt:
        print('\nStopping wheel/tire wrapper...')
    finally:
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
                        raise chassis.WrapperError('Wheel hook is live but not tracked as expected')
                    client.restore(game.pid, WHEEL_SITE)
                    if client.read_bytes(game.pid, WHEEL_SITE, 5) != WHEEL_ORIGINAL:
                        raise chassis.WrapperError('Wheel detour restoration not confirmed')
                    print('Wheel/tire JMP restored.')
                    safe_to_release = True
                elif observed == WHEEL_ORIGINAL and not matches:
                    safe_to_release = True
                else:
                    raise chassis.WrapperError('Wheel site is modified or tracked unexpectedly; '
                                               'keeping cave allocated to avoid a dangling JMP')
            except Exception as exc:
                errors.append(f'wheel restore: {exc}')
        if chassis_attempted:
            try:
                state, _ = chassis.inspect(client, game.pid)
                if state == 'APPLIED_TRACKED':
                    chassis.restore(client, game.pid)
                elif state != 'READY':
                    raise chassis.WrapperError('Chassis patch not safely restorable: ' + state)
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
        else:
            print('WARNING: code cave NOT released; wheel detour may still reference it.',
                  file=sys.stderr)
        cave.close()
        if errors:
            raise chassis.WrapperError('Cleanup incomplete. Keep WINDY/runtime open; '
                                       + ' | '.join(errors))
        print('Both hooks restored. You can exit WINDY normally.')


def main(argv=None):
    parser = argparse.ArgumentParser(description='WINDY101 chassis + wheel/tire hook (ICR2Runtime v0.13)')
    parser.add_argument('action', nargs='?', default='check', choices=('check', 'run'))
    parser.add_argument('--pid', type=int)
    parser.add_argument('--runtime-exe', help='Path to compiled ICR2Runtime v0.13, if startup is needed')
    args = parser.parse_args(argv)
    try:
        client = chassis.get_client('run' if args.action == 'run' else 'check', args.runtime_exe)
        chassis.require_runtime(client)
        game = chassis.select_game(client, args.pid)
        if args.action == 'check':
            report(client, game)
        else:
            run(client, game)
        return 0
    except (chassis.WrapperError, RuntimeCapabilityError, RuntimeStartupError,
            RuntimeErrorResponse, OSError, ValueError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
