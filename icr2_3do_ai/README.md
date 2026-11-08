# ICR2 semantic 3DO inspector (Stage 1)

A standalone **read-only analysis CLI** for agents and human reverse engineers.
This is not a second CAD viewer or 3DO parser. It calls the existing
icr2_3do_cad binary parser, N3 compiler, car appearance resolver, DYNAMIC
scene loader and material-scope logic.

It produces structured reports that can be supplied to Codex or another
coding agent without pasting thousands of raw .3D source declarations.

## Quick start

From the repository root, install the headless dependencies:

    python -m pip install numpy Pillow

Inspect a stock or modified carset:

    python -m icr2_3do_ai inspect icr2_3do_cad/fixtures/indycar.3do --objects-folder icr2_3do_cad/fixtures --texture-folder icr2_3do_cad/fixtures --views -o output/indycar_analysis

Inspect a driver wrapper in a local carset folder:

    python -m icr2_3do_ai inspect cars/his21.3do --objects-folder cars --texture-folder cars --views --source -o output/his21_analysis

Preview a driver wrapper on separately opened base carshape:

    python -m icr2_3do_ai inspect cars/indycar.3do --appearance cars/his21.3do --objects-folder cars --texture-folder cars --views -o output/his21_on_indycar

Editable N3 .3D files are accepted as input. Optional --source export can
fail for binary models whose planes cannot be represented in the supported
N3 compiler subset; omit --source in that case.

## Outputs

- **summary.json**: original input, resolved base geometry, driver appearance,
  raw-unit bounds, total counts and caveats.
- **geometry.json**: per-polygon stable IDs, original model offsets, transformed
  XYZ, UV, winding normal, area, dimensions, material provenance and
  edge-connected components.
- **scene_graph.json**: unique models and file tables, complete record trees,
  FACE/BSP plane equations, RES thresholds, DYNAMIC links, per-instance
  transforms, inherited MIP and RECOLOR context.
- **materials.json**: effective named MIP, source, assigned polygons, found MIP
  paths, header dimensions and out-of-bounds UV flags.
- **diagnostics.json**: typed warnings/errors for degeneracy, topology,
  unresolved textures or external objects.
- **views/side.png**, **views/top.png**, **views/front.png**: optional orthographic
  wireframes, not game-equivalent renders.
- **source.3D**: optional original N3 text or compilable source export.

For example, i2:p1720 is a polygon with original body offset 1720 in
instance 2, and i2:v240 is a source vertex. Use scene_graph.json to map the
instance to the original 3DO and DYNAMIC placement. Repeated external files
have distinct instance IDs.

## Important interpretation limits

- Connectivity means sharing the same original vertex-offset edge within
  the same instance, **not** matching coordinates or semantic identity.
  Separate UV seams, deliberately duplicated vertices and BSP groups can
  appear disconnected despite overlapping in 3D. A component is not
  automatically a wing, sidepod or nose cone.
- Face normals are calculated from polygon vertex winding, not from BSP plane
  semantics. They alone cannot prove a face is incorrectly oriented.
- All parsed records and RES branches are inspected, not evaluated for one
  camera. Wireframe PNGs do not use BSP selection, texture sampling, culling
  or occlusion.
- Material names follow the existing CAD's scene inheritance rules,
  including bodywork and geometric-helmet livery inheritance and the separate
  stock PMP helmet sprite path.
- MIP dimensions are checked against the header only; full MIP data is not
  decoded during inspection. UVs outside bounds can be intentional tiling.
  Missing MIPs or external models produce partial reports, not guesses.
- Compiled binary 3DOs do not preserve author-chosen source labels. Numeric
  offset labels should never be interpreted as semantic names.
- Stage 1 performs no editing, synthesis, automatic repair or AI model calls.
  Its job is providing a reproducible input for those future operations.
- No original carset files are modified. Existing report files require an
  explicit --overwrite. Generated source is written in the report folder.

## Tests

From repository root:

    python -m unittest discover -s icr2_3do_ai/tests -p 'test_*.py' -v

Headless tests use existing repository fixtures and temporary N3 models; no
API key, online services, Qt or OpenGL is required.

## Suggested agent use

Begin with summary.json, then select relevant component IDs and their polygon
records in geometry.json. Cross-reference the source model and BSP ancestry in
scene_graph.json. Require the AI to cite exact instance/record IDs, state
hypotheses separately from verified facts and preserve the original source.

Later additions can expose filtered component queries, face visibility
experiments, parametric source operations, compiler validation and in-game
comparison without replacing the existing CAD tool.
