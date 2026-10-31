# 3DO CAD contributor instructions

Scope: `icr2_3do_cad/`.

- Preserve existing editing and preview behavior; keep functional PRs focused and reversible.
- Maintain byte-identical no-op saves, conservative append-and-repoint topology edits, validation-before-replacement and existing backup semantics.
- Never silently rewrite referenced external model or texture assets while saving a parent 3DO.
- Do not remove `gamepal.pcx` or `fixtures/`: both are referenced by the editor and the tests.
- Put regression tests in `tests/`, not next to application source files.
- Run `python -m unittest discover -s tests -p "test_*.py"` from this directory, with Pillow/NumPy and a graphical display (or Xvfb) available.
- Do not commit versioned smoke scripts, temporary modified models, or saved UI screenshots. Put screenshots in an ignored `screenshots/` folder.
- Keep README user-focused; document binary invariants in `DEVELOPMENT.md`. Never infer 3DO parser correctness solely from the editor preview; verify output in-game.
