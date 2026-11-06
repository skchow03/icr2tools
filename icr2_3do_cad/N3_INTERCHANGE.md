# Editable N3 .3D text interchange

The CAD editor now exposes **File > Export editable N3 .3D text** and
**File > Import N3 .3D onto current 3DO**. Its text output uses the Papyrus
N3 \`3D VERSION 3.0;\` command family (as in
[skchow03/3do23d](https://github.com/skchow03/3do23d)).

## Fractional N3 coordinates and compile scale

The standalone N3 compiler accepts fractional vertex XYZ coordinates. A
model with fractional XYZ coordinates is interpreted using **6,000 Papyrus
units per input unit** by default, following the classic `3d23do /s=6000`
feet conversion. Integer-only models remain unscaled, preserving existing
workflows. The scale applies to both vertex XYZ and DYNAMIC XYZ, **not**
texture UVs, polygon colors or rotation angles.

For files authored in other units, add a source comment before the vertex
declarations: `% ICR2_COORD_SCALE: 19685` for meters, or
`% ICR2_COORD_SCALE: 1` for already-scaled Papyrus units. The 6,000
default is a convention, not a guarantee that every fractional source uses
feet. The model dimensions should be checked against the originating tool.

Coordinate values are rounded to the nearest signed 32-bit Papyrus integer
*after* applying the scale. When a visual editor change rewrites an N3
source, it may normalize the text into raw Papyrus integer units; keep the
original file if you want to preserve its fractional authoring notation.

## Track texture vertex spelling (t= and T=)

The N3 compiler accepts vertex UV attributes in either case. Track generators
commonly write `[<X, Y, Z>, t=<U, V>]` (lowercase `t`), while the CAD editor
normally emits uppercase `T=`. They have identical semantics. No coordinate
or UV values are altered by this compatibility change.

Malformed UV expressions still produce an explicit coordinate error, including
a short excerpt of the offending expression, rather than blaming the enclosing
FACE/BSP's plane vertices.

## Optional trailing separators in track LISTs

Trk23D may write a comma after the final object in a LIST, for example:

```text
sec5_s0_HI: FACE (a,b,c), LIST {
    DetailList_5-0H,
    DYNO { 3975781, 4373961, -150000, 390000 },
};
```

This is supported in the importer, consistent with the permissive comma
tokenization used by [nooRok's icr2_3dto3do](https://github.com/nooRok/icr2_3dto3do).
A **single final comma** is ignored when building a LIST's child pointers.
It does **not** create a NIL child or an empty child, and is retained in
the original authored source if no rewrite is needed.

The exception is limited to LISTs; incomplete interior operands such as
`LIST {a,,b}` and `LIST {,a}` remain errors. DATA and DYNO payload
validation continues to require their expected values.

## Empty track object lists

Track source generators can emit declarations such as
`ObjectList_L0_0: LIST {  };` when a section has no scenery objects.
This is a valid **zero-child LIST** node, not an invalid empty pointer
and not a synonym for `NIL`. The editor retains the LIST's named
declaration and writes an F11 record with child count 0, so references
from other section trees continue to point to a LIST.

An isolated `LIST {  }` is accepted, including whitespace/newlines.
Malformed lists such as `LIST {a,}` or `LIST {,}` still produce errors.

## Nested track BSPA prefix syntax

Tracks produced by Trk23D use prefix-operator syntax without braces around
each node. For example:

```text
section: FACE (a,b,c),
    LIST {
        BSPA (a,b,c),
            BSPA (d,e,f), left_objects, left_wall, nil,
            right_wall,
            right_objects,
        surface
    };
```

The importer groups the three child pointers for each BSPA recursively,
rather than treating every top-level comma as a new LIST sibling.
FACE/FACE2/BSPF/BSPA/BSP2/BSPN, MATERIAL and nested LISTs follow the
same rule. This prevents the false "BSPA requires a plane and 3 object
pointers" error on RENO sections.

Track `MATERIAL GROUP=N, LIST {...}` expressions can omit MIP
altogether. The editor represents these as a no-texture MATERIAL wrapper
with MIP index -1 and retains the group number. This is intended for
loading and inspection; verify binary output against the original track
compiler before using a recompiled .3DO in ICR2.

## FACE/BSP plane syntax

Papyrus N3 text defines a FACE/BSP plane using **three ordered points**,
not the five binary coefficient fields. The exporter now prefers existing
polygon vertex pointers that define exactly the same oriented plane:

```text
o1: BSPF (b2, b0, c0), nil, fr, o0;
```

When there is no exact pointer match, it uses a three-point integer
construction (derived from `3do23d/plane.py`) and writes explicit N3
coordinates, for example:

```text
o1: BSPF ([<37, 27, 0>], [<-10, 27, 0>], [<0, 27, 14>]), nil, fr, o0;
```

If an original binary plane cannot be expressed by **three exact
in-range integer points**, the export fails with an explanation rather
than silently substituting an incorrect plane. A recompiled 3DO can
still use different coefficient *magnitudes* even when the mathematical
plane is identical, so check complex scenery visibility in-game.

Legacy five-number overlays can still be imported for compatibility,
but they are never emitted as canonical N3 source.

## Editing and exporting in 3DO CAD

Use **File > Open Model…** to select a standalone `.3D` or an existing
binary `.3do`. The editable source pane retains names and comments from
text sources. Opening a binary model creates editable, compilable N3 source.
After validation, choose **File > Save .3D Source As…** to keep the text or
**File > Export Compiled 3DO…** to write a separate binary file.

Exporting compiled source can reallocate binary records and is not a
byte-preserving overlay onto the existing model. The previous application's
in-place binary-overlay import is **not** part of the current GUI. The
`text_3d.import_text` library functionality remains available to developers,
but should not be presented as a menu command.

Named pointers and `% comments` are not stored inside a binary 3DO. Retain
annotated source files and validate complex output in the original game.
See [STANDALONE_N3.md](STANDALONE_N3.md) for compiler details and limitations.
