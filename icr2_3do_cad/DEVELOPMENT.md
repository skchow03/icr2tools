# 3DO CAD development

## Architecture

The editor currently uses **flat Python modules in this directory**. Run from `icr2_3do_cad/`. Avoid renaming runtime modules without updating their direct imports.

- `icr2_3do_cad.py`: Tkinter presentation, selection, edit commands and validated file writes.
- `three_do.py`: Papyrus 3DO parser, original byte offsets, model state and binary output.
- `topology_split.py` and `geometry_add.py`: append new structures and repoint the necessary original parent pointers rather than rebuilding the BSP tree.
- `dynamic_scene.py`: read-only external model traversal and placement preview.
- `car_appearance.py`: parses car RECOLOR/material wrappers independently of geometry.
- `texture_preview.py` and `pmp_preview.py`: diagnostic rendering support; Pillow and NumPy are optional for core use.
- `raw_disassembly.py`: read-only diagnostic structure listing.

Keep `gamepal.pcx`: the GUI loads it by default. Keep `fixtures/`: tests read binary fixtures and the editor also uses the directory as an explicit fallback for external/car model resolution.

## Binary safety invariants

1. Unmodified 3DO files must be byte-for-byte identical on a no-op round-trip.
2. Preserve untouched original binary records, record offsets, child ordering and external resources.
3. Changes to topology must explicitly account for appended records and redirected pointers; do not silently rebuild the existing hierarchy.
4. Validate coordinates, plane equations, bounds, counts and references before saving.
5. Write and parse a temporary candidate before atomic replacement, retaining the existing optional backup behavior.
6. An edit to a parent or appearance preview must not implicitly rewrite referenced external files.

## Regression tests

```sh
cd icr2_3do_cad
python -m unittest discover -s tests -p "test_*.py"
```

Use Python 3.10+ with Tkinter. Texture-specific tests require `Pillow` and `numpy`; GUI tests require a desktop or Xvfb (`xvfb-run -a`). All tests live under `tests/`, with paths resolving to `../fixtures/` and `../gamepal.pcx`.

Add regression tests for new writer operations: include unchanged-byte preservation, deliberate invalid inputs, and save/reload behavior. Prefer one focused test to a new version-numbered smoke script.

Temporary screenshots belong in an ignored `screenshots/` directory. Prior release notes, throwaway smoke scripts and captured previews remain available through Git history. This cleanup intentionally does not refactor any runtime parser or GUI code.
