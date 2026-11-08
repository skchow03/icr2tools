# ICR2 3DO AI toolkit: semantic inspector + procedural N3 generator

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


---

## Stage 2 — Generate editable N3 and compiled 3DO from JSON

The Stage 2 generator is deterministic: a recipe declares geometry using
named primitives, and Python emits readable N3 vertices, polygons, LIST
groups, MATERIAL assignments, and a root LIST. The output is then compiled
through the **existing** \`n3_compile\` and independently reparsed by the
existing \`three_do.Model\` validator. There are no LLM calls or handwritten
binary 3DO structures in the generator.

**Quick start** (run from the repository root):

\`\`\`sh
python -m icr2_3do_ai generate \
  icr2_3do_ai/recipes/example_indycar_nose.json \
  -o output/example_indycar_nose --views

python -m icr2_3do_ai validate output/example_indycar_nose/model.3D
python -m icr2_3do_ai validate output/example_indycar_nose/model.3do
\`\`\`

Stage 2 creates a *new* output directory containing:

- \`recipe.json\`: exact copy of the input recipe.
- \`model.3D\`: readable, named, editable Papyrus N3 source.
- \`model.3do\`: compiled and binary-validated model.
- \`manifest.json\`: name, vertex/face counts and bounds of every component.
- \`validation.json\`: compiler/reparser results and SHA256 hashes.
- \`analysis/\`: Stage 1 semantic reports, and optionally top/front/side
  wireframes with \`--views\`.

The destination **must not already exist**. No source carsets or previously
generated outputs are overwritten. Use \`--no-analysis\` to skip reports, if
you want only the generated model and validation.

### Recipe format

The recipe has \`schema: "icr2.n3.recipe.v1"\` and a list of operations. A
\`coordinate_scale\` converts each recipe coordinate to raw Papyrus units
before source generation. For example, \`6000\` represents 6000 raw units per
input unit, consistent with the usual N3 feet convention; \`1\` is raw units.
Output source always explicitly uses \`% ICR2_COORD_SCALE: 1\` so values are
not accidentally multiplied again.

Example:

\`\`\`json
{
  "schema": "icr2.n3.recipe.v1",
  "coordinate_scale": 6000,
  "operations": [
    {
      "type": "loft", "name": "nose", "axis": "x", "color": 78,
      "sections": [
        {"at": 0, "width": 3, "height": 1.2, "center": [0, 0.8]},
        {"at": 3, "width": 1.5, "height": 0.8, "center": [0, 0.7]},
        {"at": 6, "width": 0.4, "height": 0.3, "center": [0, 0.6]}
      ],
      "material": "body",
      "uv": {
        "axes": ["x", "z"],
        "pixels_per_unit": [25, 70],
        "offset": [0, 0]
      }
    },
    {
      "type": "extrude", "name": "leftpod", "axis": "z",
      "from": 0.2, "to": 1, "color": 85,
      "outline": [[1,-4],[4,-4],[4,-2],[1,-2]]
    },
    {"type": "mirror", "name": "rightpod", "source": "leftpod", "axis": "y"}
  ]
}
\`\`\`

Operations:

| Type | Purpose | Required properties |
|---|---|---|
| \`loft\` | Connect multiple cross-sections with triangular shell faces | \`name\`, \`axis\`, \`sections\` (strictly increasing \`at\`) |
| \`extrude\` | Extrude a convex 2D outline between two planes | \`name\`, \`axis\`, \`outline\`, \`from\`, \`to\` |
| \`mirror\` | Reflect a previously created component, reversing its face winding | \`name\`, \`source\`, \`axis\`, optional plane location \`at\` |

\`loft.sections\` may use rectangular \`width\` / \`height\` / \`center\`,
or explicit \`outline: [[u,v], ...]\`; each section must contain the same
number of points with corresponding vertex ordering. \`extrude\` and \`loft\`
support \`color\` (0–255) and \`caps\` (boolean, default true).
An optional \`material\` (1–8-character MIP resource name) **must** be
paired with a planar \`uv\` projection using two world axes,
\`pixels_per_unit\`, optional \`origin\`, and optional \`offset\`.
For example, use V offsets above 255 to address extended MIP artwork.
Mirrors inherit the source material and UV rules.

Cross-sections must be strictly convex, and all loft shells are triangulated
rather than producing nonplanar quads. Vertices are quantized into signed
32-bit Papyrus coordinates. Degenerate faces, out-of-range UVs, ambiguous or
unknown fields, invalid names, excessive geometry and other invalid recipes
raise a detailed error. Maximums are 128 operations, 30,000 vertices and
60,000 faces, plus 128 rings/64 points per cross-section.

### Running through GitHub

The repository's **3DO AI semantic inspector** GitHub Actions workflow
automatically tests Stage 1 and Stage 2 when you push or open a pull request
that changes \`icr2_3do_ai/\`. It also builds every checked-in JSON recipe in
\`icr2_3do_ai/recipes/\` and publishes the generated files as the
\`3do-ai-generated-models\` Actions artifact (retained 14 days).

With the GitHub connection, you can ask ChatGPT to author or revise a recipe,
commit it on a branch, and open a PR. That commit starts the Actions build,
whose logs and output artifact can then be inspected. This is a repository
workflow, not remote execution on your PC; the action can only use assets
present in its checkout, not your unpublished local carset directory.

### Limitations and next steps

- The generator does **not** create camera-dependent BSP/FACE hierarchies,
  RES/LOD branches, external attachments, or a photogrammetrically accurate
  vehicle automatically. Generated faces are grouped under LIST nodes and
  need CAD/in-game draw-order evaluation.
- Convex section lofts and extrusions are a safe starting point; adding
  complex concave meshes, UV-unwrapping and multi-material face groups is
  future work.
- The generator does not import, replace, or mutate an existing carshape:
  it emits a new separate model, suitable for later composition in N3.
- \`--views\` produces diagnostic wireframes, **not** game-accurate renders.
- Compiler validation proves syntax and binary structural consistency, **not**
  historical shape fidelity, visibility from all camera angles or in-game
  compatibility.

To run all tests locally:

\`\`\`sh
python -m unittest discover -s icr2_3do_ai/tests -p 'test_*.py' -v
\`\`\`
