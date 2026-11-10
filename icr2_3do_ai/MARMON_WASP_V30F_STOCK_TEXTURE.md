# Marmon Wasp V30f: stock-compatible carshape textures

## Evidence from user-supplied roadcar.3do

Binary header and reachable record inspection found a SUPEROBJ root, five immediate DYNAMIC objects (four wheels and helmet), 31 textured POLY[T] records all with group 16, zero MIP header entries, and no MATERIAL records in the common carshape. Its main scene uses a multi-LOD RES/BSP object. The V30e Wasp instead used LIST root, group 0, and an embedded MARMON MATERIAL. The CPU viewer rendered that construction, but the ICR2 game did not.

The repository's stock individual-car appearance parser confirms a separate driver appearance .3do (e.g. ind96.3do) has root MATERIAL containing a paint MIP, child RECOLOR, and a shared carshape EXTERN filename.

## V30f files

- WASP.3do: SUPEROBJ root, one primary body/shadow LIST plus five direct DYNAMIC parts. No MIP table and no MATERIAL nodes. 63 POLY[T] polygons in group 16. All 372 polygons, XYZs, UVs, colors, the 80 FACE gates, V30d shadow and raised neck remain unchanged. The five parts are no longer duplicated in the primary body branch.
- MARMON.3do: a separate appearance wrapper with root MATERIAL MIP="MARMON", child RECOLOR identity entries, and WASP external geometry in its file table. Editable sources are included for both.
- MARMON.mip: exact original 128x165 user atlas with 7 LODs. SHA256: 46a6a8bd7e0cd969417710a51c10fa7be8bfa727dcb5935566f178ac12e06d39.
- FWHEEL.3do, RWHEEL.3do, HELMET.3do: unchanged.

Atlas mapping remains: radiator U 0..47 V 0..42; bonnet U 47..127 V 0..72; tail U 47..127 V 74..127; number on both tail-fin sides U 104..127 V 131..154.

## Compiler and verification

The native N3 compiler now accepts the opt-in source comment `% ICR2_CAR_TEXTURE_GROUP: 16` to emit stock group 16 for textured POLYs while leaving legacy sources at group 0. No binary patch is used. CI checks compiler backwards compatibility, the SUPEROBJ root and five immediate DYNAMIC children, 63 group-16 textured faces, absence of carshape MIP/MATERIAL records, 80 FACE gates, and identity of polygon geometry/UVs to V30e. The MARMON wrapper is parsed with the repository's standard car-appearance reader. Thirteen CPU views use the explicit appearance wrapper.

## Installing and testing

Crucial: placing WASP.3do and MARMON.mip in a directory is not sufficient to select the paint. ICR2 needs to load the chosen driver's appearance .3do, which must reference MARMON as its MIP and WASP as its external carshape. MARMON.3do is a reference appearance wrapper; it is NOT selected automatically merely because it exists. In a stock-style carset, use the actual driver appearance slot filename, and back up original files before replacing anything. Carset DAT packaging and roster selection are installation-specific and not verified here.

The Wasp's SUPEROBJ primary scene is a LIST rather than the reference roadcar's RES; it is not a byte-for-byte structural clone. External parts move outside the previous BSP painter tree, so in-game helmet/tail and radiator occlusion must be retested. CPU previews do not prove real game rendering.

Build command: `python -m icr2_3do_ai.wasp_v30f_stock_carshape --baseline /path/to/v30e --output /path/to/v30f`.