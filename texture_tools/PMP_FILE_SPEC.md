# Papyrus PMP sprite file specification

This document describes the PMP sprite variant read and written by the
`texture_tools` package. It is an implementation-oriented specification based
on the package's encoder and decoder, rather than a claim about every PMP file
used by every Papyrus title. Fields whose original meaning is not established
are explicitly identified as unknown.

## Overview

A PMP is a palette-indexed sprite stored as horizontal, single-colour runs in a
256 by 256 coordinate space. It contains no palette and no per-pixel alpha.
Colour values must be resolved through an external 256-colour palette, normally
the track's `SUNNY.PCX`. Pixels not covered by a run are transparent.

All multibyte integers used by the tools are unsigned and little-endian. The
file has a fixed 12-byte header followed immediately by zero or more 4-byte run
records. It has no magic number, version, or end marker.

```text
+----------------------+ 0x00
| 12-byte header       |
+----------------------+ 0x0C
| run record 0         |
+----------------------+
| run record 1         |
+----------------------+
| ...                  |
+----------------------+ end of file
```

## Header

| Offset | Size | Type | Name | Description |
| ---: | ---: | --- | --- | --- |
| `0x00` | 1 | `uint8` | bounding width | Width of the non-transparent bounding box. The tools write the value modulo 256, so `0` can represent a width of either zero or 256. |
| `0x01` | 1 | `uint8` | bounding height | Height of the non-transparent bounding box. The tools write the value modulo 256, so `0` can represent a height of either zero or 256. |
| `0x02` | 1 | `int8` / opaque | horizontal origin | Normally the negated x coordinate of the bounding box's left edge, encoded as a signed 8-bit value. See [Origin override](#origin-override). |
| `0x03` | 1 | `int8` / opaque | vertical origin | Normally the negated y coordinate of the bounding box's top edge, encoded as a signed 8-bit value. See [Origin override](#origin-override). |
| `0x04` | 4 | `uint32le` | run-data size | Number of bytes in the run payload. A canonical file therefore has `(file size - 12)` here, and the value is a multiple of four. |
| `0x08` | 4 | opaque bytes | unknown field | Preserved as an uninterpreted four-byte value. The encoder default is `1E 00 00 00`. |

The header's bounding dimensions and origin describe sprite metadata; they do
not constrain the run-coordinate space. The decoder renders runs onto a
256 by 256 transparent canvas and only uses the bounding box when reporting
metadata.

### Origin override

In its normal mode, the encoder computes the opaque-pixel bounding box and
writes `-left` at `0x02` and `-top` at `0x03`, using two's-complement signed
bytes. For example, a bounding box beginning at `(10, 20)` produces `F6 EC`,
which represents `(-10, -20)` as `int8` values.

The encoder also exposes a legacy `size_field` override. When it is nonzero,
its complete `uint16le` value replaces bytes `0x02..0x03`; those bytes must then
be treated as opaque because they no longer contain independently calculated
origins. This option exists for compatibility and does not establish the
original semantic meaning of that 16-bit value.

For a fully transparent image the encoder writes zero for both bounding
dimensions and both origin bytes.

## Run payload

Each record paints one half-open horizontal interval with one palette index:

| Record offset | Size | Type | Name | Description |
| ---: | ---: | --- | --- | --- |
| `+0` | 1 | `uint8` | `y` | Row in the 256 by 256 sprite coordinate space. |
| `+1` | 1 | `uint8` | `x_start` | First painted x coordinate. |
| `+2` | 1 | `uint8` | `x_end_exclusive` | Coordinate immediately after the last painted pixel. |
| `+3` | 1 | `uint8` | `palette_index` | Index into the external 256-colour palette. |

A valid, nonempty run satisfies `x_start < x_end_exclusive` and paints pixels
for which `x_start <= x < x_end_exclusive`. The current decoder ignores a run
when `x_start > x_end_exclusive`; an equal start and end naturally paints no
pixels. Producers should emit only strictly increasing intervals.

The encoder scans rows from top to bottom and pixels from left to right. On each
row it emits one maximal run for every sequence of adjacent, non-transparent
pixels having the same palette index. Transparent pixels and palette-index
changes end a run. Consumers should not require this canonical ordering: every
record contains an absolute row and x interval.

All record fields occupy one byte. In particular, the tools do not define a
sentinel interpretation for an `x_end_exclusive` value of zero. Producers using
this specification should therefore keep run endpoints in the representable
range `1..255`; a run ending at atlas coordinate 256 cannot be represented
unambiguously by the implementation documented here.

## Transparency and colour

PMP records carry only palette indices. There is no special transparent palette
index: transparency is represented by the absence of a run at a pixel.

When converting RGBA input, the encoder treats alpha values less than or equal
to its configured transparency threshold as transparent. Other pixels are
quantized to the selected external palette. The default threshold is zero, so
only fully transparent pixels are omitted. Alpha above the threshold is not
preserved; decoded run pixels are fully opaque.

The PMP file does not identify its palette. Correct colours depend on decoding
with the same palette used to quantize the source. The tools accept a
256-colour PCX palette; the decoder also accepts a raw palette consisting of at
least 768 bytes in RGB triplet order. For raw palettes whose largest component
is at most 63, the decoder scales VGA-range components from `0..63` to
`0..255`.

## Worked example

The following 28-byte file represents four runs. The opaque bounding box is
4 pixels wide by 2 pixels high, the origin is `(0, 0)`, and the run payload is
16 bytes:

```text
Offset  Bytes                                      Meaning
------  -----------------------------------------  ---------------------------
0000    04 02 00 00                                bbox 4x2, origin (0,0)
0004    10 00 00 00                                16 payload bytes
0008    1E 00 00 00                                unknown/default field
000C    00 00 02 01                                y=0, x=[0,2), colour 1
0010    00 02 04 02                                y=0, x=[2,4), colour 2
0014    01 00 01 03                                y=1, x=[0,1), colour 3
0018    01 01 04 04                                y=1, x=[1,4), colour 4
```

With a palette mapping indices 1 through 4 to `A`, `B`, `C`, and `D`, the
decoded two-row region is:

```text
A A B B
C D D D
```

## Reader validation recommendations

A strict reader should:

1. Reject files shorter than 12 bytes.
2. Compare the `uint32le` payload size at `0x04` with the bytes remaining after
   the header.
3. Require the effective payload length to be divisible by four.
4. Reject or skip records with `x_start >= x_end_exclusive`.
5. Bounds-check every interval before drawing it.
6. Treat bytes `0x08..0x0B` as opaque and avoid assigning semantics without
   evidence from additional game files.

The package decoder is deliberately tolerant: it warns about payload-size and
alignment discrepancies, parses complete 4-byte records, skips reversed or
non-painting runs, and clips intervals to its 256 by 256 canvas. A strict tool
may instead reject these conditions, but should report which invariant failed.

## Known limitations and open questions

- No signature identifies a file as PMP, so validation relies on structure and
  plausible field values.
- The original meaning of header bytes `0x08..0x0B` is unknown.
- The legacy nonzero `size_field` interpretation at `0x02..0x03` is unknown.
- A zero bounding dimension is ambiguous between empty and 256 pixels; runs
  and application context are needed to distinguish them.
- The supplied tools establish a 256 by 256 coordinate space but do not
  establish a safe on-disk encoding for a half-open run ending at x=256.
- Run overlap behavior is not defined by the file itself. The package decoder
  applies records in file order, so later records overwrite earlier pixels.
