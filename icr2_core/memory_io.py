"""Helper functions for reading typed values from an ``ICR2Memory`` instance."""
from __future__ import annotations

from typing import List, Optional, Protocol, Sequence


class MemoryLike(Protocol):
    def read(self, addr: int, kind: str, count: int | None = None):  # pragma: no cover - protocol only
        ...


def read_i32(mem: MemoryLike, addr: int) -> Optional[int]:
    """Read a single i32 value from ``mem``.

    Returns ``None`` when the read fails or the buffer is shorter than four bytes.
    """

    raw = mem.read(addr, "i32", count=1)
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        if len(raw) < 4:
            return None
        return int.from_bytes(raw[:4], "little", signed=False)
    if isinstance(raw, Sequence):
        return int(raw[0]) if raw else None
    try:
        iterator = iter(raw)  # type: ignore[arg-type]
    except TypeError:
        return None
    first = next(iterator, None)
    return int(first) if first is not None else None


def read_i32_list(mem: MemoryLike, addr: int, count: int) -> List[int]:
    """Return up to ``count`` i32 values from ``mem`` as a list."""

    raw = mem.read(addr, "i32", count=count)
    if raw is None:
        return []
    if isinstance(raw, int):
        return [raw]
    if isinstance(raw, (bytes, bytearray)):
        length = len(raw) // 4
        return [
            int.from_bytes(raw[i * 4:(i + 1) * 4], "little", signed=False)
            for i in range(length)
        ]
    try:
        return [int(x) for x in raw]  # type: ignore[arg-type]
    except Exception:
        return []
