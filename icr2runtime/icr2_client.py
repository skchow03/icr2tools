"""Read-only Python client for ICR2Runtime v0.11 (Windows, no third-party packages).

One request per named-pipe connection. The C++ service caches the game handles,
so connecting for each request no longer initiates a memory signature scan.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import struct

PIPE_NAME = r"\\.\pipe\ICR2Runtime_v11"
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
ERROR_BROKEN_PIPE = 109
ERROR_PIPE_BUSY = 231
ERROR_NO_PROCESS = 233

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateFileW.argtypes = (
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE
)
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.WaitNamedPipeW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD)
kernel32.WaitNamedPipeW.restype = wintypes.BOOL
kernel32.WriteFile.argtypes = (
    wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p
)
kernel32.WriteFile.restype = wintypes.BOOL
kernel32.ReadFile.argtypes = (
    wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p
)
kernel32.ReadFile.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
kernel32.CloseHandle.restype = wintypes.BOOL


@dataclass(frozen=True)
class Game:
    pid: int
    version: str
    translation_base: int
    host_module_base: int
    window_title: str


class RuntimeErrorResponse(RuntimeError):
    """Server replied ERR, rather than completing a read."""


def request(command: str) -> str:
    """Send one ASCII request to C++ and retrieve its full UTF-8 response."""
    if "\n" in command or "\r" in command or not command.isascii():
        raise ValueError("Requests must be a single ASCII line")
    handle = kernel32.CreateFileW(PIPE_NAME, GENERIC_READ | GENERIC_WRITE,
                                  0, None, OPEN_EXISTING, 0, None)
    if handle == INVALID_HANDLE_VALUE or handle is None:
        code = ctypes.get_last_error()
        if code == ERROR_PIPE_BUSY and kernel32.WaitNamedPipeW(PIPE_NAME, 3000):
            handle = kernel32.CreateFileW(
                PIPE_NAME, GENERIC_READ | GENERIC_WRITE,
                0, None, OPEN_EXISTING, 0, None)
        if handle == INVALID_HANDLE_VALUE or handle is None:
            raise ctypes.WinError(ctypes.get_last_error())

    try:
        payload = (command + "\n").encode("ascii")
        buffer = ctypes.create_string_buffer(payload)
        written = wintypes.DWORD(0)
        if not kernel32.WriteFile(handle, buffer, len(payload),
                                  ctypes.byref(written), None):
            raise ctypes.WinError(ctypes.get_last_error())
        if written.value != len(payload):
            raise OSError("Incomplete named-pipe request write")

        chunks: list[bytes] = []
        total = 0
        while True:
            block = ctypes.create_string_buffer(16384)
            received = wintypes.DWORD(0)
            if not kernel32.ReadFile(handle, block, len(block),
                                     ctypes.byref(received), None):
                error = ctypes.get_last_error()
                if error in (ERROR_BROKEN_PIPE, ERROR_NO_PROCESS):
                    break  # End-of-response from server (Windows dependent)
                raise ctypes.WinError(error)
            if not received.value:
                break
            chunks.append(block.raw[:received.value])
            total += received.value
            if total > 1024 * 1024:
                raise ValueError("Server response exceeds 1 MiB")
        return b"".join(chunks).decode("utf-8", errors="replace")
    finally:
        kernel32.CloseHandle(handle)


def _payload(response: str) -> str:
    if response.startswith("ERR\t"):
        raise RuntimeErrorResponse(response.strip())
    if not response.startswith("OK\t"):
        raise RuntimeErrorResponse("Unexpected/empty response: " + repr(response[:80]))
    return response[3:].strip()


class ICR2Client:
    def capabilities(self) -> set[str]:
        return set(_payload(request("CAPS")).split(","))

    def patch_data(self, pid: int, address: int, expected: bytes, new: bytes) -> None:
        """Guarded in-memory DATA patch, with old bytes required to match."""
        if not expected or len(expected) > 8 or len(expected) != len(new):
            raise ValueError("Patches must contain 1-8 bytes of identical length")
        _payload(request(f"PATCH {pid} {address:X} {expected.hex()} {new.hex()}"))

    def map_file_offset(self, pid: int, file_offset: int) -> int:
        return int(_payload(request(f"MAP {pid} {file_offset:X}")), 16)

    def patch_code(self, pid: int, address: int, expected: bytes, new: bytes) -> None:
        if not expected or len(expected) > 8 or len(expected) != len(new):
            raise ValueError("Code patches must contain 1-8 bytes of identical length")
        _payload(request(f"PATCHCODE {pid} {address:X} {expected.hex()} {new.hex()}"))

    def restore(self, pid: int, address: int) -> None:
        _payload(request(f"RESTORE {pid} {address:X}"))

    def list_patches(self) -> list[tuple[int, int, str, bytes, bytes]]:
        lines = request("PATCHES").splitlines()
        count = int(_payload(lines[0]))
        patches = []
        for line in lines[1:]:
            parts = line.split("\t")
            if len(parts) != 6 or parts[0] != "PATCH":
                raise RuntimeErrorResponse("Invalid PATCHES response")
            patches.append((int(parts[1]), int(parts[2], 16), parts[3],
                            bytes.fromhex(parts[4]), bytes.fromhex(parts[5])))
        if len(patches) != count:
            raise RuntimeErrorResponse("PATCHES count mismatch")
        return patches

    def ping(self) -> bool:
        return _payload(request("PING")) == "PONG"

    def refresh(self) -> None:
        _payload(request("REFRESH"))

    def list_games(self) -> list[Game]:
        lines = request("LIST").splitlines()
        if not lines:
            raise RuntimeErrorResponse("Empty LIST response")
        count = int(_payload(lines[0]))
        games: list[Game] = []
        for line in lines[1:]:
            parts = line.split("\t", 5)
            if len(parts) != 6 or parts[0] != "GAME":
                raise RuntimeErrorResponse("Invalid GAME record: " + repr(line))
            games.append(Game(int(parts[1]), parts[2], int(parts[3], 16),
                              int(parts[4], 16), parts[5]))
        if count != len(games):
            raise RuntimeErrorResponse("Mismatched LIST game count")
        return games

    def read(self, pid: int, address: int, kind: str = "i32") -> int | float:
        if kind not in {"u8", "i8", "u16", "i16", "u32", "i32",
                        "u64", "i64", "f32", "f64"}:
            raise ValueError("Unsupported numeric type: " + kind)
        result = _payload(request(f"READ {pid} {address:X} {kind}"))
        return float(result) if kind.startswith("f") else int(result)

    def read_bytes(self, pid: int, address: int, size: int) -> bytes:
        if not 1 <= size <= 65536:
            raise ValueError("BULK requests must be 1..65536 bytes")
        hex_data = _payload(request(f"BULK {pid} {address:X} {size}"))
        result = bytes.fromhex(hex_data)
        if len(result) != size:
            raise RuntimeErrorResponse("BULK response length mismatch")
        return result

    def read_struct(self, pid: int, address: int, fmt: str) -> tuple:
        """Read one packed struct; e.g. '<ii' for two little-endian i32 values."""
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.read_bytes(pid, address, size))


class ICR2Session:
    """Reusable named-pipe session. Not safe for concurrent use by multiple threads."""
    def __init__(self):
        self.handle = None

    def __enter__(self):
        handle = kernel32.CreateFileW(PIPE_NAME, GENERIC_READ | GENERIC_WRITE,
                                      0, None, OPEN_EXISTING, 0, None)
        if handle == INVALID_HANDLE_VALUE or handle is None:
            raise ctypes.WinError(ctypes.get_last_error())
        self.handle = handle
        self._send("SESSION")
        if self._receive() != "OK\tSESSION\n":
            self.close()
            raise RuntimeErrorResponse("SESSION handshake failed")
        return self

    def _send(self, command: str):
        if not command.isascii() or "\n" in command or "\r" in command:
            raise ValueError("Single-line ASCII command required")
        payload = ctypes.create_string_buffer((command + "\n").encode("ascii"))
        count = wintypes.DWORD()
        if not kernel32.WriteFile(self.handle, payload, len(payload)-1,
                                  ctypes.byref(count), None) or count.value != len(payload)-1:
            raise ctypes.WinError(ctypes.get_last_error())

    def _exact(self, length: int) -> bytes:
        parts = []
        while length:
            chunk = ctypes.create_string_buffer(min(length, 16384))
            count = wintypes.DWORD()
            if not kernel32.ReadFile(self.handle, chunk, len(chunk),
                                     ctypes.byref(count), None) or not count.value:
                raise ctypes.WinError(ctypes.get_last_error())
            parts.append(chunk.raw[:count.value])
            length -= count.value
        return b"".join(parts)

    def _receive(self) -> str:
        header = self._exact(9)
        if header[-1:] != b"\n":
            raise RuntimeErrorResponse("Invalid session frame")
        length = int(header[:8], 16)
        if length > 1024*1024:
            raise RuntimeErrorResponse("Oversized session response")
        return self._exact(length).decode("utf-8")

    def request(self, command: str) -> str:
        self._send(command)
        return self._receive()

    def read_bytes(self, pid: int, address: int, size: int) -> bytes:
        if not 1 <= size <= 65536: raise ValueError("Size out of range")
        return bytes.fromhex(_payload(self.request(f"BULK {pid} {address:X} {size}")))

    def close(self):
        if self.handle is not None:
            kernel32.CloseHandle(self.handle)
            self.handle = None

    def __exit__(self, *_):
        self.close()


def _client_scan(self, pid: int, start: int, length: int, pattern: bytes,
                 limit: int = 64) -> list[int]:
    if not 1 <= len(pattern) <= 32 or not 1 <= length <= 16*1024*1024 or not 1 <= limit <= 256:
        raise ValueError("SCAN accepts a 1-32 byte pattern, 1-16MiB span and 1-256 matches")
    lines = request(f"SCAN {pid} {start:X} {length} {pattern.hex()} {limit}").splitlines()
    count = int(_payload(lines[0]))
    values = [int(x.split("\t")[1],16) for x in lines[1:] if x.startswith("HIT\t")]
    if len(values) != count: raise RuntimeErrorResponse("SCAN response mismatch")
    return values


def _client_batch(self, pid: int, patches: list[tuple[int,bytes,bytes]]) -> None:
    if not 1 <= len(patches) <= 32: raise ValueError("PATCHBATCH accepts 1-32 patches")
    fields = []
    for address, before, after in patches:
        if not 1 <= len(before) <= 8 or len(before) != len(after):
            raise ValueError("Each patch must contain 1-8 bytes")
        fields.append(f"{address:X}:{before.hex()}:{after.hex()}")
    _payload(request(f"PATCHBATCH {pid} {len(fields)} " + " ".join(fields)))


ICR2Client.scan = _client_scan
ICR2Client.patch_batch = _client_batch


def _client_patch24(self, pid: int, address: int, expected: bytes, replacement: bytes) -> None:
    """Guarded, tracked 24-byte DATA record replacement; restores via restore().

    Both payloads must contain exactly 24 bytes, typically six signed i32s.
    This method deliberately does not support executable-page writes.
    """
    if len(expected) != 24 or len(replacement) != 24:
        raise ValueError("PATCH24 requires exactly 24 expected and replacement bytes")
    _payload(request(f"PATCH24 {pid} {address:X} {expected.hex()} {replacement.hex()}"))


def _client_patch_object6(self, pid: int, address: int, expected: tuple[int, ...],
                          replacement: tuple[int, ...]) -> None:
    """Write six little-endian signed 32-bit object fields at one address."""
    if len(expected) != 6 or len(replacement) != 6:
        raise ValueError("Object records must have exactly six integer fields")
    self.patch24(pid, address, struct.pack('<6i', *expected), struct.pack('<6i', *replacement))

ICR2Client.patch24 = _client_patch24
ICR2Client.patch_object6 = _client_patch_object6


# Animation leases: registration snapshots original bytes, updates keep the
# snapshot, and end restores them. Use a persistent session for frame updates.
def _anim_begin(self, pid: int, address: int, original: bytes):
    if len(original) != 24: raise ValueError("ANIM_BEGIN requires 24 bytes")
    _payload(self.request(f"ANIM_BEGIN {pid} {address:X} {original.hex()}"))

def _anim_update(self, pid: int, address: int, current: bytes):
    if len(current) != 24: raise ValueError("ANIM_UPDATE requires 24 bytes")
    _payload(self.request(f"ANIM_UPDATE {pid} {address:X} {current.hex()}"))

def _anim_end(self, pid: int, address: int):
    _payload(self.request(f"ANIM_END {pid} {address:X}"))

for _klass in (ICR2Client, ICR2Session):
    _klass.anim_begin = _anim_begin
    _klass.anim_update = _anim_update
    _klass.anim_end = _anim_end

ICR2Client.request = staticmethod(request)
