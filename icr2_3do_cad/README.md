# ICR2 3DO CAD

The ICR2 3DO CAD editor is the supported application for inspecting and editing Papyrus *IndyCar Racing II* and *CART Racing* `.3D` source and `.3DO` models. It uses a PySide6 desktop interface and an OpenGL 3.3 renderer for large car, object and track models. The former Tkinter front end has been retired.

## Run

Install **Python 3.10+**, an OpenGL 3.3-capable driver and the dependencies:

```sh
python -m pip install -r icr2_3do_cad/requirements.txt
python icr2_3do_cad/icr2_3do_cad.py
python icr2_3do_cad/icr2_3do_cad.py path/to/model.3d
```

Alternatively, from inside `icr2_3do_cad/`, run `python icr2_3do_cad.py`. On Windows, `RUN_ME_WINDOWS.bat` launches this same application. No separate renderer or subfolder entry point is required.

To measure viewport performance, use `--benchmark` and optionally `--report cad_profile.json`. The normal editor does not continuously redraw when idle.

## Features

- Open compiled `.3do` files or standalone Papyrus/N3 `.3D` source; the editable source panel recompiles and updates the viewport after validation.
- Car, Track and Object workspaces; camera orbit, pan, zoom, orthographic and fixed-camera views, track-guided navigation, indexed HI/MED/LO section windows and optional skybox.
- Inspect vertex and polygon source declarations, BSP/draw-order decisions, external DYNAMIC models, MIP materials, PMP sprites and visibility.
- Preview a separate driver `.3do` RECOLOR and body MIP on the currently editable car or car-part geometry without opening the driver's referenced carshape.
- Edit N3 source with live diagnostics, reference navigation, polygon splitting, vertex inspection, pointer renaming and scaling.
- Save source or export a newly compiled `.3do` explicitly; failed compilation does not overwrite game assets.

## Preview a driver appearance on an editable car model

Open `roadcar.3do`, `indycar.3do`, a wheel, or another car-part geometry file.
Choose **Assets → Apply Individual-Car RECOLOR / MIP…**, then choose an
individual-car file such as `cit74.3do`. The **Car Settings** dialog offers the
same command, plus **Clear appearance overlay**.

The viewport applies the driver file's RECOLOR mapping and resolves its named
body MIP relative to the driver file, while you continue editing the original
geometry and .3D Source. A wrapper's own geometry reference is intentionally
ignored for this explicit overlay: `cit74.3do` can be previewed on
`roadcar.3do` despite referencing `indycar.3do`. External wheel/helmet
materials remain independent. The overlay is **preview-only**: exporting
compiled geometry does not embed the wrapper's RECOLOR/MIP or rewrite it.
If a body MIP is missing, the MIP diagnostics identify it. A separate manual
body-MIP override takes precedence until cleared.

**Important:** Exporting edited source recompiles a model; binary record offsets may change. Back up originals, validate new assets, and test compiled models in-game. The renderer is a diagnostic approximation, not a game-exact rasterizer.

See the [full user guide](USER_GUIDE.md), [N3 interchange notes](N3_INTERCHANGE.md), [development and binary-safety notes](DEVELOPMENT.md) and [performance guide](PERFORMANCE.md).

## Tests

From `icr2_3do_cad/`:

```sh
python -m unittest discover -s tests -p 'test_*.py'
```

GUI/OpenGL tests require a display and their dependencies. On headless Linux, use `xvfb-run` with Mesa software rendering. GitHub Actions exercises both the general regression suite and an OpenGL framebuffer smoke test.

The bundled `fixtures/` and `gamepal.pcx` are required by the editor and tests.
