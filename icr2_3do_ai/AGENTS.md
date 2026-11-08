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

## Stage 3 modeled design jobs

- Modeling plans are declarative JSON proposals, not an instruction channel
  granting permission to run arbitrary Python or download remote assets.
- A plan's goal is documentation only. The assistant must convert design
  intent into validated template parameters or Stage 2 operations; the CLI
  does not understand unstructured English itself.
- Keep vintage-racer templates explicitly illustrative. Do not claim exact
  Marmon Wasp shapes, dimensions, colors or technical details without
  documented period references and user validation.
- Revisions operate **only on Stage 2 JSON recipes**. Never imply they patch
  arbitrary binary 3DOs, replace hidden BSP nodes, or preserve byte offsets.
  The candidate source is compiled anew into separate output assets.
- The code must preserve untargeted components, enforce quality limits and
  verify old/new source through the existing N3 compiler/3DO parser.
- Keep baseline and candidate source, validation results and geometry
  diagnostics in the CI artifact. Never auto-merge PRs into main or modify
  game data outside the new output directory.
- Add headless tests for invalid plans, path traversal, stale baseline
  hashes, mirror dependencies and no-overwrite behavior.
