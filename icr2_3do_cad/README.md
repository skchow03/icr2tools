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
