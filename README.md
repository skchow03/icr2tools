# ICR2Tools
A suite of modern modding utilities for *IndyCar Racing II*, by SK Chow.

## Structure
- **icr2_core/** – shared library (memory access, DAT/TRK readers, models)
  - [Architecture](icr2_core/ARCHITECTURE.md)
- **icr2timing/** – live telemetry overlay app
  - [Architecture](icr2timing/ARCHITECTURE.md)
- **track_viewer/** – experimental desktop utility for browsing track files
  - [Architecture](track_viewer/ARCHITECTURE.md)

## Install (for development)
```bash
pip install -e .
```

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

### ICR2 Timing Overlay
Launch the legacy overlay (control panel + in-game overlay) with:

```bash
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
python -m track_viewer
# or, after ``pip install .``
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

### Texture Tools

Texture Tools provides texture conversion and editing workflows in one desktop
application. The Sunny Optimizer is included as a tab within Texture Tools rather
than as a standalone command.

Launch the application with:

```bash
texture-tools
# or
python -m texture_tools.main
```
