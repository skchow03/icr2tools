from __future__ import annotations

import numpy as np

from icr2_core.trk.sg_classes import SGFile


def create_empty_sgfile() -> SGFile:
    header = np.array(
        [int.from_bytes(b"\x00\x00GS", "little"), 1, 1, 0, 0, 0],
        dtype=np.int32,
    )
    xsect_dlats = np.array([-300_000, 300_000], dtype=np.int32)
    num_xsects = len(xsect_dlats)
    header[5] = num_xsects
    return SGFile(header, 0, num_xsects, xsect_dlats, [])
