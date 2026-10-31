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
