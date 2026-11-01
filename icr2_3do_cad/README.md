# ICR2 3DO CAD Editor

A Python/Tkinter editor for Papyrus *IndyCar Racing II* / *CART Racing* `.3do` models. The current application is **v1.9**. It supports model inspection and carefully limited binary editing; it is not a pixel-identical reproduction of the game renderer.

## Run

Install Python 3.10+ with Tkinter. From `icr2_3do_cad/`:

```sh
python icr2_3do_cad.py
python icr2_3do_cad.py fixtures/roadcar.3do
```

On Windows, double-click `RUN_ME_WINDOWS.bat` instead. On some Linux systems install `python3-tk`. A graphical desktop is required.

**Optional textured previews:** `python -m pip install Pillow numpy`. Without these packages the editor still launches and supports solid-color rendering. The supplied `gamepal.pcx` is the default 256-color palette.

Use **File → Open** for your own geometry 3DO or supported car-appearance/RECOLOR wrapper. The bundled `fixtures/` models also serve as repeatable examples and fallback external car parts.

## UI workflow

The upper toolbar keeps **Open**, **Save Copy**, **Undo**, and **Redo** available in every editing mode. Use the **Vertex**, **Polygon**, or **Part** selection buttons to decide what a click in the viewport selects; the right-hand panel shows the selected element and its relevant properties.

Use the **3D**, **Top**, **Front**, and **Side** camera presets; **Frame All (F)** fits the entire model, while **Frame Selection (Shift+F)** centers and zooms on the selected vertex, polygon, or external part. Right-drag to orbit and scroll to zoom.

The **Display…** control reveals the detailed LOD, BSP, lighting, projection, and texture preview settings. The top **Technical details** checkbox shows the underlying model statistics. In the Polygon tab, use **Show advanced splitting / BSP tools** for low-level split operations and plane edits.

Editing still uses the original 3DO data, and saving remains an explicit validated **Save Copy** operation with the existing overwrite/backup safeguards.

## Vertex pointer names and viewport labels

Opening a human-authored **.3D** preserves vertex declaration names such as
`front_left` or `b2`. The Vertex inspector displays each name as an editable
**Pointer name** attribute, and the vertex list and selection header show it
alongside the current binary body offset. To rename a vertex, select it and
use **Rename**; the editor changes the declaration and all references in
the .3D source without rewriting comments or quoted filenames.

Use **Vertex labels → Off / Names / Offsets** on the viewport toolbar,
or **View → Vertex labels**, to control on-screen labeling. In Names mode,
unnamed vertices fall back to their numeric offsets. For large models,
on-screen labels are spaced apart and capped to avoid unreadable overlapping
text; the selected vertex is always identifiable.

Pointer names remain attached to the source declaration through vertex
XYZ and texture UV changes, undo/redo, and normal source recompilation.
They are **not** matched by coordinate, since texture seams can duplicate
XYZ positions. New or deleted vertex declarations update the available
names. A binary .3DO has no authored pointer names, so they initially
remain blank when opening a .3DO directly, although you may assign names
in the inspector for subsequent .3D exports.

**Keep your annotated .3D source.** The binary .3DO format does not store
pointer names, so reopening only the .3DO cannot recover them.

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

## Live .3D source editing

The **.3D Source** tab contains an editable Papyrus/N3 text document,
including named pointers, MIP declarations, geometry and `% comments`.
Typing is parsed **after 650 ms of inactivity** on a background thread.
A successful parse updates the 3D viewport and the Vertex, Polygon, Parts,
Create and Raw panels. The editor never displays a half-parsed model:
when a statement cannot be parsed it highlights the likely line and retains
the most recently valid preview until the text is corrected.

**Apply now** forces immediate validation, and **Find error** scrolls to the
highlighted statement. **Save .3D…** saves the editable source, including
unfinished work; **Save Copy** produces a binary `.3do` **only after the
source successfully validates**. External MIPs are still loaded separately
for textured previews. No parser or text editor can prove a complex BSP
model looks correct in ICR2; verify the saved result in-game.

Opening a `.3do` automatically generates editable N3 source text as well.
Once you edit that source, the editor compiles a new working model, so
original binary record offsets may be reallocated; a source-text recompile
is **not** a byte-identical patch. For conservative original-offset changes,
use the separate **File → Import N3 .3D onto current 3DO** workflow.

Visual edits also update the text. Before switching away from Source, an
unfinished text edit is validated; if invalid, fix the highlighted statement
first. Parser errors should be resolved before making additional visual edits.
The original `.3D` source file is never overwritten automatically.

## Large track .3D files (RENO-style)

The standalone N3 loader also accepts track files using a `3D VERSION 3.0`
header **without** a trailing semicolon, hyphenated names such as
`DetailP_0-1`, nested FACE/BSP/MATERIAL/LIST trees, large `DATA`
hash tables and a final `index: LIST { ... };` root.

The editor compiles the model in memory; a complete track may have tens of
thousands of N3 source lines, so initial compilation, annotation and first
viewport rendering can be substantially slower than for a car or building.
Vertex pointer names remain attached to the original declarations.

The generic 3DO binary parser does not expose the length of track hash-table
DATA records. When editing an original standalone track source, its full
named `DATA` declarations are retained in edited .3D exports rather than
silently truncating them to four integers. Continue keeping the original
source and test any separately compiled 3DO in-game. Track-specific drawing
order, surfaces and external MIP/3DO resources are not automatically fixed
by loading a text source.

## Open standalone N3 .3D models

You can now open a Papyrus/N3 `.3D` text file **directly**, without first
loading any binary `.3do`. Select it from **File → Open…** or
**File → Open standalone N3 .3D…**. The editor compiles a validated
in-memory model; use **Save Copy** to create a binary `.3do`.
Original labels and comments remain in the text source. See
[N3_INTERCHANGE.md](N3_INTERCHANGE.md) for supported syntax and limitations.

## N3 .3D text interchange

Choose **File → Export editable N3 .3D text** to obtain a Papyrus/N3
`.3D` source file similar to the output of
[3do23d](https://github.com/skchow03/3do23d).
You can annotate the file with `% comment` lines and rename record labels
to meaningful identifiers. Keep each `% ICR2_OFFSET: N` identity comment
above its declaration so the CAD importer can still find the matching binary
record, even after renaming pointers.

To reimport, **open the original `.3DO`**, then choose
**File → Import N3 .3D onto current 3DO**. Imported values appear in the
editor immediately; use **Save Copy** to write a validated binary. Labels and
comments remain in the `.3D` text source, not inside `.3DO`.

For now this round-trip handles existing records and value edits. Adding or
deleting geometry or changing BSP/LIST pointer topology in text requires a
full compiler; the importer rejects those edits rather than guessing.
See [N3_INTERCHANGE.md](N3_INTERCHANGE.md) for supported edits and limitations.

## Capabilities

- Edit existing vertices, polygon base palette colors, UV coordinates and polygon/BSP plane properties.
- Split existing polygons and append new geometry through conservative, structure-preserving binary edits.
- Preview LOD/distance selection, LIST order, FACE/FACE2/BSP visibility, MIP textures and PMP helmet sprites.
- Inspect external DYNAMIC components such as wheels and helmets, with editable parent-side placement transforms.
- Review a read-only raw structure listing, validate proposed output, and optionally back up an existing destination.

The display is a diagnostic approximation. Always inspect edited output **in the game** and keep original models backed up. Edits to the parent model do not intentionally rewrite external wheel, helmet or car-appearance files.

## Essential files

| File / directory | Purpose |
| --- | --- |
| `icr2_3do_cad.py` | Tkinter GUI and application entry point |
| `three_do.py` | Binary 3DO model parser and validated editing |
| `topology_split.py` | Polygon topology splitting |
| `geometry_add.py` | Append-and-repoint new geometry |
| `dynamic_scene.py` | External DYNAMIC model traversal |
| `car_appearance.py` | RECOLOR appearance wrapper reading |
| `texture_preview.py`, `pmp_preview.py` | MIP/PMP previews |
| `raw_disassembly.py` | Read-only raw structure listing |
| `gamepal.pcx` | Bundled palette, used by the GUI |
| `fixtures/` | Test models and GUI fallback model assets |
| `tests/` | Automated regression suite |

## Tests

From `icr2_3do_cad/`:

```sh
python -m unittest discover -s tests -p "test_*.py"
```

GUI tests require a display. On headless Linux, use `xvfb-run -a python -m unittest discover -s tests -p "test_*.py"`. Texture tests need Pillow and NumPy.

See [DEVELOPMENT.md](DEVELOPMENT.md) for technical constraints and [AGENTS.md](AGENTS.md) for contributor guidance. Version-by-version notes, experimental smoke scripts and old screenshots are recoverable in Git history instead of cluttering the active source directory.
