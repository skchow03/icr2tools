from __future__ import annotations

from icr2_core.trk.sg_classes import SGFile

BOUNDARY_KIND = "wall"  # "wall" or "armco"


def create_empty_sgfile() -> SGFile:
    header: list[int] = [int.from_bytes(b"\x00\x00GS", "little"), 1, 1, 0, 0, 0]
    xsect_dlats: list[int] = [-300_000, 300_000]
    num_xsects = len(xsect_dlats)
    header[5] = num_xsects
    return SGFile(header, 0, num_xsects, xsect_dlats, [])
