# ICR2Tools

A suite of modern modding utilities for *IndyCar Racing II*, by SK Chow.

## Included tools

- **sg_viewer/** – SG track geometry editor and viewer
  - [Architecture](sg_viewer/architecture.md)
- **track_viewer/** – track previewer, camera editor, and AI-line tools
  - [Architecture](track_viewer/ARCHITECTURE.md)
- **texture_tools/** – texture conversion, editing, and palette optimization
- **icr2timing/** – live telemetry overlay
  - [Architecture](icr2timing/ARCHITECTURE.md)
- **icr2runtime/** – Windows C++ memory-access service for supported ICR2 builds
  - [Setup, Python API, developer reference and license](icr2runtime/README.md)
- **icr2multicar/** – single-script WINDY per-car chassis and wheel/tire hooks
  - [Installation, usage and compatibility](icr2multicar/README.md)
- **icr2_core/** – shared memory, DAT, TRK, MIP, and conversion code
  - [Architecture](icr2_core/ARCHITECTURE.md)
- **icr2_3d_catalog_viewer/** – track 3D catalog viewer
- **tso_generator/** – trackside-object generator

## Development setup

ICR2Tools requires Python 3.9 or newer. Create and activate a virtual
environment, then install the repository in editable mode:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
```

Run the test suite from the repository root with `python -m pytest`.

## Generated files

The following ignored directories contain generated or machine-local data and
can be safely deleted when the associated application is not running:

- `screenshots/` – generated screenshots and captured previews.
- `exports/` – user-requested exports that should not be committed.
- `build/` and `dist/` – packaging and build artifacts.
- `local_settings/` – machine-specific settings and overrides.
- `logs/` – application log output.
- `repo_dumps/` – generated repository snapshots.
- `telemetry_laps/` – recorded timing and telemetry data.

These directory names are ignored wherever they occur in the working tree, so
tools may create them beside the relevant application. Fixed runtime files such
as `icr2timing/timing_log.txt`, `track_viewer/track_viewer_log.txt`, timestamped
`telemetry_laps_*.csv` files, and `track_viewer/repo_dump_v2.txt` are ignored as
well. File types are not ignored globally: PNG assets, JSON fixtures, CSV and
TXT examples, and default INI configuration files remain trackable.

## Tools

### SG Viewer

Launch the SG track geometry editor with:

```bash
sg-viewer
# or
python -m sg_viewer
```

In **Surface → Surface Detail → TSD Objects**, assign each object a **TSD File**
by editing its table cell or attributes. **Export all to .TSD** asks for an output
folder and combines objects with the same filename into that file, in table order.
The `.tsd` extension is optional. Export warns and stops if any object has no
filename; existing output files require overwrite confirmation. Assignments are
saved in the `.sgc` project and retained when duplicating objects.

### ICR2 Multi-Car Models

Run the Windows-only `icr2multicar/icr2multicar.py` script with
**ICR2Runtime v0.13** and native WINDY101. It supports read-only inspection
and applies the chassis and wheel/tire hooks together; see the
[Multi-Car Models guide](icr2multicar/README.md) for setup, commands, and
safety limitations.

### ICR2 Timing Overlay
Launch the legacy overlay (control panel + in-game overlay) with:

```bash
icr2-timing
# or
python -m icr2timing.main
```

### Track Viewer
The track viewer is a PyQt desktop tool for inspecting IndyCar Racing II track
folders. It:

- Discovers tracks in the `TRACKS/` directory and previews the `.TRK` ground
  surface with centreline overlays.
- Loads `.cam`/`.scr` data from disk or bundled DAT files, allowing Type 6/7
  camera editing, TV mode reshuffling, coordinate tweaks, and save/export back
  to disk (with optional DAT repacking).
- Displays AI line (`*.LP`) polylines and lets you toggle individual files.
- Runs the `trk_gaps` check against the loaded track and surfaces the results
  inline.

Run it either as a module or via the installed entry point:

```bash
python -m track_viewer.main
# or, after `pip install .`
track-viewer
```

### TRK to 3D converter

Generate a Papyrus text track surface from a binary `.TRK` file:

```bash
trk23d path/to/track.trk [path/to/track.3D]
# or
python -m icr2_core.trk.trk23d_cli path/to/track.trk
```

The converter writes HI, MED, and LO ground meshes plus the section DLONG
lists, hash data, and final index expected by track `.3D` source files.

### TSO Generator

For grandstands, **Crowd Pieces** splits the sloped crowd surface into equal
pieces along its length. Each piece repeats the full texture rectangle specified
by **Crowd Upper Left (U, V)** and **Crowd Lower Right (U, V)**, so longer stands
can repeat the crowd texture instead of stretching it across the whole stand.
**Crowd MIP Filename** accepts a name such as `crowd` or `crowd.mip`; export emits
`MATERIAL MIP="crowd", GROUP=3, POLY [T]` on each crowd polygon with the matching
vertex UVs. Leave the filename blank for plain polygons. These settings are
saved with project objects and templates. New objects default to one piece,
`crowd`, and UV corners `(0, 0)` / `(255, 63)`; existing objects without crowd
settings keep their single, untextured surface.

Grandstands also provide palette selectors for **Front Color**, **Sides Color**
(both ends), **Back Color**, **Crowd Color** (all crowd pieces), and
**Underside Color**. The selected colors appear in the preview and exported
polygons and are saved with the object. Existing grandstands inherit their
previous polygon colors until you change these selectors.

### Texture Tools

Texture Tools provides texture conversion and editing workflows in one desktop
application. The Sunny Optimizer is included as a tab within Texture Tools rather
than as a standalone command.

In **Convert from source**, select a PMP sprite to adjust its alpha cutoff with
the slider. Each sprite's percentage (default 33%) is saved automatically as
`alpha_cutoff_percent` in the source folder's `sunny_optimizer.json`. **Apply
cutoff to all PMPs** copies the current value to every PMP in that folder; you can
then adjust individual sprites further. Preview and conversion use each sprite's
saved cutoff.

PMP previews and exports use the same palette conversion and alpha cutoff.
Pixels above the cutoff retain their original RGB color before palette matching
and become fully opaque; pixels at or below it are omitted. Partial alpha is
never blended against black, so it does not darken the exported sprite edges.

Launch the application with:

```bash
texture-tools
# or
python -m texture_tools.main
```
