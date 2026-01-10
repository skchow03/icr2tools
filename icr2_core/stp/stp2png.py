#!/usr/bin/env python3
"""
stp2png.py

ICR2 STP decoder with hybrid RLE rules and HARD DEBUG MODE.

Features:
- Hybrid RLE:
    a <= 64        : literal run (a)
    65 <= a < 128  : repeat run (a - 64)
    a >= 128       : repeat run (a - 128)
- On decode error:
    * logs rich diagnostic info
    * STILL writes a PNG
    * fills remaining pixels with a debug color (0xFF)
"""

from __future__ import annotations

import argparse
import logging
import struct
from pathlib import Path
from typing import List

from PIL import Image


# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------

LOGGER_NAME = "stp2png"


def setup_logger(log_path: Path | None, verbose: bool) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    if log_path:
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger


# -----------------------------------------------------------------------------
# Core
# -----------------------------------------------------------------------------

class STPDecodeError(Exception):
    pass


def read_pcx_256_palette(pcx_path: Path) -> List[int]:
    data = pcx_path.read_bytes()
    if len(data) < 769 or data[-769] != 0x0C:
        raise STPDecodeError("Invalid or missing 256-color PCX palette")
    return list(data[-768:])


def decode_stp_partial(
    stp_path: Path,
    logger: logging.Logger,
) -> tuple[int, int, bytearray, int]:
    """
    Returns:
        width, height,
        decoded pixel buffer (partial),
        stop_offset (file offset where decoding failed or ended)
    """
    buf = stp_path.read_bytes()
    width, height = struct.unpack_from("<HH", buf, 0)

    total = width * height
    out = bytearray()
    offset = 8

    logger.debug("Decoding %s (%dx%d)", stp_path.name, width, height)

    try:
        while len(out) < total:
            if offset >= len(buf):
                raise STPDecodeError("Unexpected EOF")

            ctrl_offset = offset
            a = buf[offset]
            offset += 1

            # ---------------- Literal ----------------
            if a <= 64:
                run_len = a
                if run_len == 0:
                    raise STPDecodeError("Literal run length 0")

                if offset + run_len > len(buf):
                    raise STPDecodeError("EOF in literal run")

                out.extend(buf[offset : offset + run_len])
                offset += run_len

            # ---------------- Repeat a - 64 ----------------
            elif a < 128:
                run_len = a - 64
                if run_len <= 0:
                    raise STPDecodeError("Repeat length <= 0 (a-64)")

                if offset >= len(buf):
                    raise STPDecodeError("EOF reading repeat color")

                color = buf[offset]
                offset += 1
                out.extend([color] * run_len)

            # ---------------- Repeat a - 128 ----------------
            else:
                run_len = a - 128
                if run_len <= 0:
                    raise STPDecodeError("Repeat length <= 0 (a-128)")

                if offset >= len(buf):
                    raise STPDecodeError("EOF reading repeat color")

                color = buf[offset]
                offset += 1
                out.extend([color] * run_len)

    except STPDecodeError as e:
        logger.error(
            "DECODE STOPPED at file offset 0x%08X\n"
            "  control byte = 0x%02X (%d)\n"
            "  decoded px   = %d / %d\n"
            "  reason       = %s",
            ctrl_offset,
            a,
            a,
            len(out),
            total,
            str(e),
        )
        return width, height, out, ctrl_offset

    return width, height, out, offset


def write_partial_png(
    width: int,
    height: int,
    pixels: bytearray,
    palette: List[int],
    out_path: Path,
    logger: logging.Logger,
    fill_color: int = 0xFF,
) -> None:
    total = width * height

    if len(pixels) < total:
        missing = total - len(pixels)
        logger.warning(
            "Filling %d missing pixels with debug color 0x%02X",
            missing,
            fill_color,
        )
        pixels.extend([fill_color] * missing)

    img = Image.frombytes("P", (width, height), bytes(pixels))
    img.putpalette(palette)
    img.save(out_path)

    logger.info("Wrote partial PNG: %s", out_path)


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser("STP → PNG (partial output on error)")
    ap.add_argument("stp", type=Path)
    ap.add_argument("pcx", type=Path)
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--log", type=Path)
    ap.add_argument("-v", "--verbose", action="store_true")

    args = ap.parse_args()
    logger = setup_logger(args.log, args.verbose)

    out_path = args.out if args.out else args.stp.with_suffix(".png")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    palette = read_pcx_256_palette(args.pcx)

    width, height, pixels, stop_offset = decode_stp_partial(args.stp, logger)

    write_partial_png(
        width,
        height,
        pixels,
        palette,
        out_path,
        logger,
    )


if __name__ == "__main__":
    main()
