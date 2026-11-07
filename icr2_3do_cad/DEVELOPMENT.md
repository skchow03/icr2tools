# 3DO CAD development

## Architecture

The sole application entry point is `icr2_3do_cad.py` in this directory. It runs the PySide6/OpenGL editor (Python 3.10+). Its viewport, source editing, UI, car/track and texture modules now live alongside the existing 3DO parser and N3 compiler. There is no second front end.

- `icr2_3do_cad.py`: Qt main window, OpenGL viewport, load/save/export commands and model workspaces.
- `mesh.py`, `scene.py`, `textures.py`, `sprites.py`, `sprite_gl.py`, `skybox.py`, `track_lod.py`, `track_navigation.py`: scene construction, rendering and navigation.
- `source_tab.py`, `source_*.py`, `active_source.py`, `polygon_split.py`: live N3 source editing, validation, inspections and source transformations.
- `three_do.py`, `n3_compile.py`, `text_3d.py`, `n3_plane_points.py`: binary 3DO and N3 source compiler/interchange.
- `dynamic_scene.py`, `car_appearance.py`, `texture_preview.py`, `pmp_preview.py`: model/asset decoding reused by the renderer.
- `tracing_reference.py`, `tracing_reference_dialog.py`, `tracing_reference_gl.py`: pure 2D point-to-model-plane calibration, local photo UI and a separate GL_RGBA8 background pass. The pass must never enter scene polygons, binary output, depth picking or source compilation.
- `fixtures/`, `gamepal.pcx`: required sample files and default palette.

The application uses flat imports relative to this directory. Direct execution of `python icr2_3do_cad.py` and the Windows batch launcher must work without a separate Python package.

## Binary safety invariants

1. Unmodified binary `.3do` parsing and byte-preserving `Model.build_modified_bytes()` operations must remain non-destructive.
2. Preserve original records, offsets, ordering and references for direct binary edits; append/repoint topology rather than rewriting unrelated records.
3. Validate coordinates, planes, bounds, counts and references before writing.
4. Never silently overwrite an original `.3D` or `.3do`; exports must be explicitly requested by the user.
5. Source recompilation can regenerate offsets and ordering. Do not confuse it with a byte-identical binary patch.
6. Do not modify external models or textures while exporting a parent model.

## DYNAMIC preview orientation

Binary DYNAMIC angles are stored in Z/Y/X slots (`+0x10`, `+0x14`, `+0x18`). The preview applies them to column vectors as `Rz(Z) * Ry(-Y) * Rx(X)`: only the rendering interpretation of the second signed angle is negated. Do not swap the Y and X slots or alter stored angles.

Stock Vancouver `pitsuite.3do` provides one orientation check; the X-angle sign is not independently verified across all objects. Preserve the existing convention until contradicted by a reproducible example.

## Regression checks

From this directory, run `python -m unittest discover -s tests -p 'test_*.py'`. Run graphical tests with `xvfb-run -a`, PySide6, PyOpenGL, Pillow and NumPy. Use `python smoke_test.py fixtures/roadcar.3do` in an OpenGL 3.3-capable environment. For source/compiler changes, confirm saved results in the game as well as in the editor.

Keep local screenshots in the ignored `screenshots/` directory. Temporary models and benchmark reports are not source assets.
