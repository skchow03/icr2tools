# ICR2 3DO AI contributor instructions

Scope: icr2_3do_ai/.

The inspector is a read-only consumer of icr2_3do_cad, not another 3DO
binary parser or a GUI. Preserve all source game binaries and sibling assets.
Reports must only be written under explicitly requested output directories;
do not silently overwrite existing analysis or source files.

Keep stable instance and original body-record offsets in JSON. Distinguish
geometric adjacency from subjective component identification. Geometric normals
are not proof of FACE/BSP visibility. Missing dependencies are incomplete
analysis, not confirmed absent game components.

Run the headless tests from the repository root:

    python -m unittest discover -s icr2_3do_ai/tests -p 'test_*.py' -v

Do not depend on an LLM, network access, Qt, or OpenGL for core inspection.

## Stage 2 procedural N3 generation

- `parametric.py` handles declarative JSON shapes, not hand-authored opaque
  shell commands or executable Python supplied in recipes.
- Validate operation names, schema, units, source component references, convex
  outlines, polygon winding, UV range and signed coordinate limits.
- Output explicit `% ICR2_COORD_SCALE: 1` with already-quantized raw XYZ.
  Reuse `n3_compile.compile_n3_text` and `three_do.Model` to produce and
  reparse binaries, never a second compiler or custom binary serializer.
- The Stage 2 CLI **never overwrites** any existing output directory, existing
  .3DO files or source. Temporary builds are validated before being renamed.
- Do not claim LIST-only N3 output has game-proven BSP draw order or accurate
  material/UV rendering. Manual or automated BSP validation is future work.
- Keep `icr2_3do_ai/recipes/` examples checked into the repository. GitHub
  Actions compiles them and publishes build artifacts for agent workflows.
