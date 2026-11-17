# UV-aware MIP art workbench

This workflow is for authoring ICR2 car liveries against the existing model's
real UV coordinates, rather than asking an image model to invent a complete
texture sheet. It is headless and uses the existing semantic inspector, CAD
MIP decoder and ICR2 MIP encoder. There is no new 3DO/MIP binary parser.

## 1. Export the actual template

From the root of icr2tools (install numpy and Pillow):

    python -m icr2_3do_ai.mip_workbench export \
      --model path/to/indycar.3do \
      --mip path/to/ind95.mip \
      --palette path/to/gamepal.pcx \
      --objects-folder path/to/cars1911 \
      -o output/wasp_art

This writes a new directory:

- base.png: existing high-resolution MIP level with the selected palette
- uv_guide.png: exact-size transparent UV edges
- uv_preview_4x.png: nearest-neighbor enlarged image for inspection
- manifest.json: source polygon IDs, real UV vertices/bounds,
  material assignments, palette and MIP hashes, out-of-bounds polygons,
  and number of atlas pixels covered by multiple polygons

With an unusual wrapper/material name, supply --material followed by the
MATERIAL name; with a driver wrapper also supply --appearance. The default
selection matches the input MIP stem, falling back to CAD inspector's
body-paintable polygons. It does not silently include dynamic wheel or helmet
MIPs. Use the inspector's geometry.json to identify a material if needed.

Do not infer part names from polygons automatically. A visually obvious
radiator, cowl, bonnet, cockpit or number fin must be labeled after checking
the UV preview and actual model.

## 2. Generate or draw each part separately

For AI-generated art, generate an orthographic tile, not a perspective
photograph of the assembled car. Specify the tile's orientation, target
aspect ratio, repeat direction and salient details. Generate the source art
larger than its target size, then downsample with the deterministic tool.
Use vector or manually rasterized art for numerals and pinstripes.

Example plan (coordinates illustrative only; verify against the target model's
UV manifest before use):

    {
      "schema": "icr2.mip.art-plan.v1",
      "layers": [
        {
          "name": "radiator",
          "rect": [0, 0, 48, 43],
          "art": "radiator.png",
          "fit": "stretch"
        },
        {
          "name": "bonnet",
          "rect": [47, 0, 80, 73],
          "art": "bonnet.png",
          "fit": "stretch"
        }
      ]
    }

Rectangles are [x, y, width, height] in source MIP texels, including the
top-left corner. PNG paths are relative to the JSON plan. Art with transparency
preserves underlying pixels. Stretch maps the full art tile to the rectangle;
contain retains aspect ratio with transparent margins. Overlapping art
rectangles are rejected, so consolidate any intentionally shared area.

## 3. Build a new MIP without touching the original

    python -m icr2_3do_ai.mip_workbench build \
      --project output/wasp_art \
      --plan path/to/paint_plan.json \
      -o output/ind95_new.mip

The tool refuses to overwrite existing files, checks baseline MIP and palette
hashes, limits new colors to palette indices 32–175 by default, and preserves
EVERY original base-level palette index outside nontransparent art-slot pixels.

It uses the existing carset MIP encoder for downsampled LODs and then restores
exact level-zero indices. It rereads the generated MIP to verify its base
image byte-for-byte. It saves ind95_new.png and ind95_new_report.json, including
count of changed pixels outside declared art slots (must be zero).

Lower-resolution mip levels are regenerated. This does not prove a perfect
visual match or correct in-game appearance. The UV preview is NOT a game
screenshot. Use the actual target carset palette, not a guessed palette.
The safe range may be changed with --min-index and --max-index.

## 4. Compare the car, not just the atlas

1. Load the compiled 3DO and new MIP into the existing 3DO CAD, with the
   same palette as in-game. Check side, top, front and oblique views.
2. Look for seams, mirrored/reversed numbers, undersides, UV overlaps and
   LOD-induced disappearance of small stripes or numbers.
3. Run an in-game test for BSP/FACE order, far-side visibility, helmets and
   wheel occlusion. A UV overlay cannot certify these.
4. Make specific corrections: named part, verified UV rectangle, pixel range
   and evidence screenshot. Avoid repainting unrelated regions.

If no verified UV mapping exists, map the polygon before generating art.
Historical color names do not assign bodywork regions or exact hues.
