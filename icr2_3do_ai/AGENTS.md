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

## Phase 1 geometry integrity (generic Stage 2)

- Prefer one continuous external shell to overlapping lofts. Don't rely on
  painter-order overrides to conceal buried bonnet/cowl geometry.
- Use independent `caps: {"start": false, "end": true}` when only the visible
  cockpit-facing closure is needed. Do not manufacture end caps merely to
  delete them later in a model-specific assembler.
- Use `type: "polygon"` for zero-thickness fins/signs rather than an
  extrusion followed by removal of thickness faces. Concave flat sheets
  are triangulated; convex sheets remain single N3 POLYs.
- Review `manifest.surface_checks` findings before delivery. Use
  `surface_checks: "error"` for clean new non-overlapping parts where
  accidental intersections must fail CI. Warnings are conservative,
  can describe intentional overlays, and do NOT prove a general solid
  intersection or BSP visibility defect.
- Never automatically delete inward-facing faces: exposed cockpit lining,
  seat closures and radiator interiors may be intentionally visible.
  Remove faces only after examining topology and viewing requirements.
- Preserve previous source and binary behavior for existing recipes. New
  schema fields are optional and legacy bool caps retain both-end semantics.



## Phase 2 structured assembly (generic Stage 2)

- The \`assembly\` block is optional. Do not change the emitted source for
  recipes lacking it, nor silently migrate \`assemble_wasp.py\`.
- Use \`assembly.py\` to assemble named geometry, transformation groups,
  anchors, external DYNAMIC objects, named FACE gates and a typed painter
  graph. Never implement new regex substitutions of \`*_p0037\` labels in a
  model-specific assembler as a substitute for structured geometry selection.
- Every transform is in explicitly declared source/game coordinate space.
  Convert decimal recipe units to integers once; Z quarter-turn rotations
  are exact, uniform scale must preserve integer coordinates. Reject unknown
  angle conventions, nonuniform scale and ambiguous coordinate frames.
- Keep a single render-path instance of every component and external:
  unique membership, no graph cycles, no missing or duplicate painter leaves.
  Use named anchors for attachments; moving a driver group also moves its
  helmet DYNAMIC, but not unrelated fixed cockpit surfaces.
- N3 \`DYNAMIC ... EXTERN\` names are model basenames, at most eight ASCII
  characters; declare and record .3do dependencies, and validate actual
  external files when \`--objects-folder\` is supplied. Do not embed or
  overwrite stock wheels, helmets, or PMP assets.
- FACE plane winding must pass explicit positive/negative sample camera
  halfspace tests. Compilation validates syntax/structure, **not** all
  Papyrus runtime visibility semantics; BSPA/BSPN are view-dependent
  painter operations, not geometric mesh repair.
- Phase 1 surface-integrity diagnostics run **after** component transforms.
  Do not hide doubled skins or broken topology by changing painter order.
- Keep \`phase2_assembly_demo.json\` compiling in CI and retain Wasp V29
  build/palette/geometry checks without a migration. Run \`test_assembly.py\`.


## Phase 3 camera-specific filled previews and image differences

- Use \`python -m icr2_3do_ai preview\` to inspect compiled FACE/BSP ordering
  and PMP sprite placements from fixed orthographic cameras. Reuse the CAD
  parser, scene transforms, MIP and PMP decoders; never add another 3DO parser
  or reimplement the rasterizer's binary interpretation.
- Use \`compare\` with matching camera names, a common frame, identical palette,
  fixed dimensions and asset locations. Review all before/after/diff/three-panel
  PNGs plus \`comparison.json\` before claiming that a painter issue was fixed.
  For reproducibility, preserve baseline binaries and declare resource files.
- Missing MIP, PMP and EXTERN resources must be surfaced as diagnostics.
  Use \`--strict-assets\` when claiming complete sprite/camera coverage.
  Do not infer absent geometry from a missing dependency.
- Output is diagnostic and orthographic, not a true Papyrus software renderer.
  Passing image comparison alone does not prove in-game correctness or repair
  overlapping surfaces. Do not silently modify previous binaries to 'match'
  a baseline; leave V29 preserved unless a migration is requested.
- CI should render actual stock helmet PMP fixtures, compile examples, compare
  unchanged models at exact zero mismatch and publish inspectable PNG reports.
