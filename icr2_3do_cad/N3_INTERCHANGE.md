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

## Open a standalone .3D (no source binary required)

Use **File > Open…** and select any supported Papyrus/N3 `.3D`, or select
**File > Open standalone N3 .3D…**. The editor now compiles a validated model
directly from the text. The original `.3D` stays untouched; **Save Copy**
produces a new binary `.3do`. Named pointers and `% comments` remain
in the text source, even though binary 3DO has no fields for them.

This new standalone compiler supports a documented subset of N3, including
new vertex/polygon declarations and hierarchical LIST/FACE/BSP operations.
See [STANDALONE_N3.md](STANDALONE_N3.md) for details and limitations.

## Existing binary-overlay workflow

The following workflow remains useful when you explicitly want to patch the
*original* 3DO without changing any of its binary record layout.

1. Open the original **binary** \`.3do\` in the CAD editor.
2. Export a \`.3D\` text file. Edit coordinates, UVs, polygon colors, raw
   FACE/BSP coefficients, DYNAMIC positions/rotations, labels and comments.
3. Keep each \`% ICR2_OFFSET: 123\` line immediately above its declaration,
   even when renaming \`_123:\` to something descriptive like \`front_wing:\`.
   Change corresponding references when renaming pointers.
4. With the original binary model open, import the edited \`.3D\`.
   Validation is **transactional**: a bad edit does not change the model.
5. Inspect the result in the viewport and choose **Save Copy** to write the
   validated \`.3do\`. Keep the \`.3D\` separately as the annotated source.

Papyrus \`.3DO\` binary stores numeric pointers and geometry, **not** label
names or text comments. When the edited \`.3D\` is imported and then exported
again in the same editor session, the editor retains its labels and comments
wherever possible. Reopen the text source when beginning a new editing session.

## Binary-overlay limitations

The **overlay import** is intentionally an **in-place binary patch**, not a general
\`.3D\` compiler. It supports edits to original record values, but **does not
yet compile added/deleted vertices or polygons, reordered LIST entries,
rewired BSP pointers, new resource references, or altered record flavors**.
These are rejected explicitly rather than silently corrupting the binary.

The original source \`.3do\` must be loaded and its body offsets must match the
\`.3D\` text file. \`3do23d\` exports using \`_123\` names can be mapped without
annotations; renamed names need \`% ICR2_OFFSET\` annotations from CAD export.
The numeric raw-plane representation is used to avoid inaccurate automatic
plane reconstructions. This is N3-style text interchange, but full validation
by external Papyrus/Noorok 3D compilers remains recommended.

As with any 3DO edit, save to a separate copy and test the result in-game.
