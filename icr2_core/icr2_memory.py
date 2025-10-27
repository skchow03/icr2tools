"""
icr2_memory.py — Minimal, efficient typed memory reader/writer for ICR2 inside DOSBox.

What this module does:
  • Attaches to DOSBox by window-title keywords and computes the ICR2 EXE base via signature scan.
  • Provides unified, typed read/write APIs: read(offset, type, count=1) and write(...).
  • Provides BulkReader to prefetch a contiguous region once and slice many fields (zero extra syscalls).
  • Provides read_blocks() for N×K table layouts with optional stride/padding.
  • Cleans up process handles and supports `with ICR2Memory(...) as mem:`.

Configurable via settings.ini:
  • memory.version = REND32A or DOS
  • memory.window_keywords = comma-separated window title substrings (case-insensitive)

Signature bytes/offset are **not** configurable — they are fixed internally.
"""

from __future__ import annotations

import logging
log = logging.getLogger(__name__)


import ctypes
import ctypes.wintypes
import struct
from collections.abc import Iterable
from typing import List, Optional, Tuple

import pymem
import win32gui
import win32process
import os, configparser
import sys

# ----------------------------
# Config
# ----------------------------

_cfgdir = os.path.dirname(sys.argv[0])
_cfgfile = os.path.join(_cfgdir, "settings.ini")
_parser = configparser.ConfigParser()
_parser.read(_cfgfile)

# ----------------------------
# Win32 virtual memory basics
# ----------------------------

MEM_COMMIT = 0x1000
PAGE_READABLE = (0x02 | 0x04 | 0x08 | 0x20 | 0x40)  # PAGE_READONLY etc.

class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ('BaseAddress', ctypes.wintypes.LPVOID),
        ('AllocationBase', ctypes.wintypes.LPVOID),
        ('AllocationProtect', ctypes.wintypes.DWORD),
        ('RegionSize', ctypes.c_size_t),
        ('State', ctypes.wintypes.DWORD),
        ('Protect', ctypes.wintypes.DWORD),
        ('Type', ctypes.wintypes.DWORD),
    ]


# ----------------------------
# Window discovery + signature
# ----------------------------

def find_pid_by_window_title(keywords: List[str]) -> Optional[dict]:
    """
    Return {'pid': int, 'title': str} for the first visible window whose title contains
    ALL given keywords (case-insensitive). Returns None if not found.
    """
    result = {'pid': None, 'title': None}

    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if all(k.lower() in title.lower() for k in keywords):
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                result['pid'] = pid
                result['title'] = title
                raise StopIteration
        return True

    try:
        win32gui.EnumWindows(callback, None)
    except StopIteration:
        pass

    return result if result['pid'] else None


def _scan_region_chunked(pm: pymem.Pymem, start: int, size: int,
                         needle: bytes, chunk_size: int = 64 * 1024) -> Optional[int]:
    if size <= 0 or not needle:
        return None
    end = start + size
    overlap = max(0, len(needle) - 1)
    leftover = b""
    pos = start
    while pos < end:
        to_read = min(chunk_size, end - pos)
        try:
            chunk = pm.read_bytes(pos, to_read)
        except Exception:
            pos += to_read
            leftover = b""
            continue
        data = leftover + chunk
        idx = data.find(needle)
        if idx != -1:
            return (pos - len(leftover)) + idx
        leftover = data[-overlap:] if overlap else b""
        pos += to_read
    return None


def find_pattern_address(pm: pymem.Pymem, pattern_bytes: bytes) -> Optional[int]:
    if not pattern_bytes:
        return None
    mbi = MEMORY_BASIC_INFORMATION()
    addr = 0
    VirtualQueryEx = ctypes.windll.kernel32.VirtualQueryEx
    while True:
        ok = VirtualQueryEx(pm.process_handle,
                            ctypes.c_void_p(addr),
                            ctypes.byref(mbi),
                            ctypes.sizeof(mbi))
        if not ok:
            break
        region_size = int(mbi.RegionSize) or 0
        if (mbi.State == MEM_COMMIT) and (mbi.Protect & PAGE_READABLE) and (region_size > 0):
            hit = _scan_region_chunked(pm, addr, region_size, pattern_bytes)
            if hit is not None:
                return hit
        addr += region_size if region_size else 0x1000
    return None

class WindowNotFoundError(RuntimeError):
    """Raised when the target DOSBox/ICR2 window cannot be found."""
    pass



# ----------------------------
# Main reader
# ----------------------------

class ICR2Memory:
    TYPE_MAP: dict[str, Tuple[str, int]] = {
        'u8':  ('<B', 1),
        'i8':  ('<b', 1),
        'u16': ('<H', 2),
        'i16': ('<h', 2),
        'u32': ('<I', 4),
        'i32': ('<i', 4),
        'f32': ('<f', 4),
        'f64': ('<d', 8),
    }

    def __init__(self,
                 version: str = None,
                 signature_bytes: Optional[bytes] = None,
                 signature_offset: Optional[int] = None,
                 window_keywords: Optional[List[str]] = None,
                 verbose: bool = True):

        # Load from INI
        ini_version = _parser.get("memory", "version", fallback=None)
        ini_keywords = _parser.get("memory", "window_keywords", fallback="")

        v = (version or ini_version or "REND32A").upper()
        if window_keywords is None:
            window_keywords = [k.strip() for k in ini_keywords.split(",") if k.strip()]

        log.info(f"Initializing memory reader for version: {v}")
        if v == "REND32A":
            window_keywords = window_keywords or ["dosbox", "cart"]
            signature_bytes = bytes.fromhex("6C 69 63 65 6E 73 65 20 77 69 74 68 20 42 6F 62")
            signature_offset = int("B1C0C", 16)
        elif v == "DOS":
            window_keywords = window_keywords or ["dosbox", "indycar"]
            signature_bytes = bytes.fromhex("6C 69 63 65 6E 73 65 20 77 69 74 68 20 42 6F 62")
            signature_offset = int("A0D78", 16)
        elif v == "WINDY":
            window_keywords = window_keywords or ["cart racing"]
            signature_bytes = bytes.fromhex("6C 69 63 65 6E 73 65 20 77 69 74 68 20 42 6F 62")
            signature_offset = int("4E2199", 16)

        else:
            log.warning(f"Unsupported version '{v}' in settings.ini")
            raise ValueError("version must be 'DOS' or 'REND32A' or 'WINDY")

        log.info(f"Searching for window with keywords {window_keywords}")
        info = find_pid_by_window_title(window_keywords)
        if not info:
            log.error(f"No matching window found for {window_keywords}")
            raise WindowNotFoundError(
                f"Could not find target window. "
                f"Looked for keywords {window_keywords}. "
                "Make sure ICR2 is running."
            )

        log.info(f"Target window found: '{info['title']}' (PID={info['pid']})")

        self.pm = pymem.Pymem()
        try:
            self.pm.open_process_from_id(info['pid'])
        except Exception as e:
            log.exception(f"Failed to open process {info['pid']}: {e}")
            raise
        log.debug(f"Opened process handle for PID {info['pid']}")

        log.debug("Scanning process memory for version signature...")

        hit = find_pattern_address(self.pm, signature_bytes)
        if not hit:
            log.error("Signature not found — memory attach failed.")
            raise RuntimeError("Signature not found in process memory")

        self.exe_base = hit - int(signature_offset)
        self.pid = info['pid']
        self.window_title = info['title']

        log.info(f"Signature found at 0x{hit:08X}, EXE base set to 0x{self.exe_base:08X}")

    # --- lifecycle / context management ---

    def close(self) -> None:
        """Safely close the process handle and release resources."""
        if not self.pm:
            log.debug("ICR2Memory.close() called, but no process handle was open.")
            return

        try:
            self.pm.close_process()
            log.info("Closed process handle cleanly.")
        except Exception as e:
            log.warning(f"Error while closing process handle: {e}", exc_info=True)
        finally:
            self.pm = None


    def __enter__(self) -> "ICR2Memory":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    # --- typed read ---

    def read(self, exe_offset: int, type_name: str, count: int = 1):
        if self.exe_base is None or self.pm is None:
            raise RuntimeError("Process not attached")
        addr = self.exe_base + int(exe_offset)
        if type_name == 'bytes':
            return self.pm.read_bytes(addr, count)
        fmt, size = self.TYPE_MAP[type_name]
        if count == 1:
            raw = self.pm.read_bytes(addr, size)
            return struct.unpack(fmt, raw)[0]
        raw = self.pm.read_bytes(addr, size * count)
        full_fmt = "<" + (fmt[1:] * count)
        return list(struct.unpack(full_fmt, raw))

    def write(self, exe_offset: int, type_name: str, value) -> None:
        """
        Write bytes or typed values to memory at exe_offset.

        * type_name == 'bytes': value must be bytes-like.
        * Otherwise value can be a single scalar or an iterable of scalars matching
          the struct format defined in TYPE_MAP.
        """
        if self.exe_base is None or self.pm is None:
            raise RuntimeError("Process not attached")

        addr = self.exe_base + int(exe_offset)

        if type_name == 'bytes':
            data = bytes(value)
        else:
            fmt, _ = self.TYPE_MAP[type_name]
            if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, str)):
                values = list(value)
                if not values:
                    return
                inner_fmt = fmt[1:]
                full_fmt = "<" + (inner_fmt * len(values))
                data = struct.pack(full_fmt, *values)
            else:
                data = struct.pack(fmt, value)

        if not data:
            return

        self.pm.write_bytes(addr, data, len(data))

    # ----------------------------
    # Bulk prefetch (contiguous)
    # ----------------------------

    class BulkReader:
        def __init__(self, icr2mem: "ICR2Memory", base_exe_offset: int, length: int):
            if icr2mem.exe_base is None or icr2mem.pm is None:
                raise RuntimeError("Process not attached")
            self._m = icr2mem
            self._base = int(base_exe_offset)
            self._len = int(length)
            self._buf = icr2mem.pm.read_bytes(icr2mem.exe_base + self._base, self._len)

        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False

        def _slice(self, exe_offset: int, size: int) -> bytes:
            rel = int(exe_offset) - self._base
            if rel < 0 or rel + size > self._len:
                raise ValueError("BulkReader slice out of range")
            return self._buf[rel:rel + size]

        def read(self, exe_offset: int, type_name: str, count: int = 1):
            if type_name == 'bytes':
                return self._slice(exe_offset, count)
            fmt, size = ICR2Memory.TYPE_MAP[type_name]
            if count == 1:
                raw = self._slice(exe_offset, size)
                return struct.unpack(fmt, raw)[0]
            raw = self._slice(exe_offset, size * count)
            full_fmt = "<" + (fmt[1:] * count)
            return list(struct.unpack(full_fmt, raw))


# ----------------------------
# Utilities
# ----------------------------

def read_blocks(mem: ICR2Memory, base_exe_offset: int,
                n_blocks: int, values_per_block: int,
                type_name: str = 'i32',
                stride_bytes: Optional[int] = None) -> List[List[int]]:
    _, tsize = ICR2Memory.TYPE_MAP[type_name]
    block_size = values_per_block * tsize
    stride = block_size if stride_bytes is None else int(stride_bytes)
    total_span = (n_blocks - 1) * stride + block_size
    out: List[List[int]] = []
    with ICR2Memory.BulkReader(mem, base_exe_offset, total_span) as br:
        for j in range(n_blocks):
            off = base_exe_offset + j * stride
            out.append(br.read(off, type_name, values_per_block))
    return out
