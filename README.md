# ICR2Tools
A suite of modern modding utilities for *IndyCar Racing II*, by SK Chow.

## Structure
- **icr2_core/** – shared library (memory access, DAT/TRK readers, models)
- **icr2timing/** – live telemetry overlay app
- **track_viewer/** – experimental desktop utility for browsing track files

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
The track viewer is a lightweight PyQt utility that scans an IndyCar Racing II
installation, lists the available `.TRK` files, and reserves space for future
visualization work. It mirrors the overlay's cleanup hooks so it can be frozen
into an executable later.

Run it either as a module or via the installed entry point:

```bash
python -m track_viewer
# or, after ``pip install .``
track-viewer
```
