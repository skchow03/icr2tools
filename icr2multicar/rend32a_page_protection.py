"""Read-only VirtualQueryEx inspection of the REND32A chassis instruction.

Requires ICR2Runtime v0.12's icr2_client.py in a sibling icr2runtime folder.
No calls to OpenProcess with VM_WRITE or VM_OPERATION; no memory modifications.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
for folder in (HERE.parent / 'icr2runtime', HERE, HERE / 'icr2runtime'):
    if (folder / 'icr2_client.py').is_file():
        sys.path.insert(0, str(folder))
        break

from icr2_client import ICR2Client

PRELUDE = bytes.fromhex('83 c0 1c 8b 00 83 c0 0c')
TAIL_PREFIX = bytes.fromhex('8b 00')
TAIL_SUFFIX = bytes.fromhex('83 c4 04 5e 5a 59 5b c3')
SCAN_START = 0x10000
SCAN_LENGTH = 0xE0000

# Windows MEMORY_BASIC_INFORMATION has slightly different 32- and 64-bit layouts.
if ctypes.sizeof(ctypes.c_void_p) == 8:
    class MEMORY_BASIC_INFORMATION(ctypes.Structure):
        _fields_ = [
            ('BaseAddress', ctypes.c_void_p),
            ('AllocationBase', ctypes.c_void_p),
            ('AllocationProtect', wintypes.DWORD),
            ('PartitionId', wintypes.WORD),
            ('_padding', wintypes.WORD),
            ('RegionSize', ctypes.c_size_t),
            ('State', wintypes.DWORD),
            ('Protect', wintypes.DWORD),
            ('Type', wintypes.DWORD),
            ('_padding2', wintypes.DWORD),
        ]
else:
    class MEMORY_BASIC_INFORMATION(ctypes.Structure):
        _fields_ = [
            ('BaseAddress', ctypes.c_void_p),
            ('AllocationBase', ctypes.c_void_p),
            ('AllocationProtect', wintypes.DWORD),
            ('RegionSize', ctypes.c_size_t),
            ('State', wintypes.DWORD),
            ('Protect', wintypes.DWORD),
            ('Type', wintypes.DWORD),
        ]

PROTECTION = {
    0x01: 'PAGE_NOACCESS',
    0x02: 'PAGE_READONLY',
    0x04: 'PAGE_READWRITE',
    0x08: 'PAGE_WRITECOPY',
    0x10: 'PAGE_EXECUTE',
    0x20: 'PAGE_EXECUTE_READ',
    0x40: 'PAGE_EXECUTE_READWRITE',
    0x80: 'PAGE_EXECUTE_WRITECOPY',
}
STATE = {0x1000: 'MEM_COMMIT', 0x2000: 'MEM_RESERVE', 0x10000: 'MEM_FREE'}
TYPE = {0x20000: 'MEM_PRIVATE', 0x40000: 'MEM_MAPPED', 0x1000000: 'MEM_IMAGE'}


def locate(c: ICR2Client, pid: int) -> int:
    candidates = []
    heads = c.scan(pid, SCAN_START, SCAN_LENGTH, PRELUDE, limit=256)
    for head in heads:
        tail = c.read_bytes(pid, head + 0x26, 12)
        if tail.startswith(TAIL_PREFIX) and tail.endswith(TAIL_SUFFIX):
            site = head + 0x28
            if tail[2:4] in (bytes.fromhex('89 02'), bytes.fromhex('90 90')):
                candidates.append(site)
    if len(candidates) != 1:
        raise RuntimeError(f'Expected one matching chassis function; found {len(candidates)}')
    return candidates[0]


def main() -> int:
    c = ICR2Client()
    version = c.status().get('version')
    if version != '0.12':
        raise RuntimeError(f'Expected ICR2Runtime v0.12, got {version}')
    games = [g for g in c.list_games() if g.version == 'REND32A']
    if len(games) != 1:
        raise RuntimeError(f'Expected one REND32A game, got {len(games)}')
    g = games[0]
    guest = locate(c, g.pid)
    before = c.read_bytes(g.pid, guest, 2)
    host_address = g.translation_base + guest
    if host_address < 0 or host_address > ctypes.c_size_t(-1).value:
        raise RuntimeError('Translated address outside host process pointer range')

    # Query-only access. Do not request VM_WRITE/VM_OPERATION rights.
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                        ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t]
    kernel32.VirtualQueryEx.restype = ctypes.c_size_t
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x0400, False, g.pid)  # PROCESS_QUERY_INFORMATION
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        mbi = MEMORY_BASIC_INFORMATION()
        returned = kernel32.VirtualQueryEx(handle, ctypes.c_void_p(host_address),
                                           ctypes.byref(mbi), ctypes.sizeof(mbi))
        if returned != ctypes.sizeof(mbi):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.CloseHandle(handle)

    page = mbi.Protect & 0xFF
    extra = []
    if mbi.Protect & 0x100: extra.append('GUARD')
    if mbi.Protect & 0x200: extra.append('NOCACHE')
    if mbi.Protect & 0x400: extra.append('WRITECOMBINE')
    print(f'ICR2Runtime v{version}; REND32A PID {g.pid}; READ ONLY')
    print(f'Chassis instruction (guest/Ghidra): 0x{guest:06X}; bytes: {before.hex(" ")}')
    print(f'Translation base: 0x{g.translation_base:X}')
    print(f'Actual Windows host address: 0x{host_address:X}')
    print(f'VirtualQueryEx size: {returned}; region base: 0x{mbi.BaseAddress:X}; size: 0x{mbi.RegionSize:X}')
    print(f'Allocation base: 0x{(mbi.AllocationBase or 0):X}')
    print(f'Windows protection: 0x{mbi.Protect:X} ({PROTECTION.get(page, "UNKNOWN")}' +
          (', ' + ', '.join(extra) if extra else '') + ')')
    print(f'Allocation protection: 0x{mbi.AllocationProtect:X}')
    print(f'State: {STATE.get(mbi.State, hex(mbi.State))}; type: {TYPE.get(mbi.Type, hex(mbi.Type))}')
    if mbi.State != 0x1000:
        print('ASSESSMENT: Not a committed Windows memory region. Stop; investigate.')
    elif mbi.Protect & (0x100 | 0x01):
        print('ASSESSMENT: Guarded/inaccessible page. Stop; investigate.')
    elif page in (0x02, 0x04, 0x08):
        print('ASSESSMENT: Non-executable Windows page. Current PATCHCODE rejects this class.')
    elif page in (0x20, 0x40, 0x80):
        print('ASSESSMENT: Executable Windows page. Investigate another reason for PATCHCODE failure.')
    else:
        print('ASSESSMENT: Unexpected protection. Investigate before changing any write behavior.')
    print('No patches, memory writes, or protection changes performed.')
    return 0

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        raise SystemExit(1)
