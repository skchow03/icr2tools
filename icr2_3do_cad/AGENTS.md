# 3DO CAD contributor instructions

Scope: `icr2_3do_cad/`.

- Maintain the single PySide6/OpenGL editor at `icr2_3do_cad.py`; do not reintroduce a second viewer or old Tkinter front end.
- Preserve N3 source round trips, validated exports, conservative 3DO binary edits and referenced-asset isolation.
- Do not remove `gamepal.pcx` or `fixtures/`: the application and tests require both.
- Keep tests in `tests/`, with the `test_*.py` naming convention. Run `python -m unittest discover -s tests -p "test_*.py"` from this directory.
- Qt and OpenGL tests require a display or Xvfb, PySide6, PyOpenGL, Pillow and NumPy.
- Put screenshots in ignored `screenshots/` and don't commit test-generated models or reports.
- Document user operations in README and USER_GUIDE; document binary invariants in DEVELOPMENT. Always verify compiled 3DOs in-game, not just in the viewport.
