# Editable N3 .3D text interchange

The CAD editor now exposes **File > Export editable N3 .3D text** and
**File > Import N3 .3D onto current 3DO**. Its text output uses the Papyrus
N3 \`3D VERSION 3.0;\` command family (as in
[skchow03/3do23d](https://github.com/skchow03/3do23d)).

## Workflow

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

## Current limitations

Text import is intentionally an **in-place binary patch**, not a general
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
