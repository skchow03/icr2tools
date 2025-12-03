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
