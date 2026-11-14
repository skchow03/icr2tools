# St. Petersburg temporary grandstand blockout

Reference: https://www.gpstpete.com/ and https://gpstpete.com/seating-guide ; St. Pete uses temporary reserved grandstands. This is an illustrative reusable straight-section module, **not** a dimensionally surveyed Grandstand 3–7.

- Coordinate scale: 6,000 raw ICR2 units per foot. Length X=36 ft, depth Y=18 ft, low front Z≈3 ft, high rear Z≈13.55 ft.
- Components: 12 stepped bench strips, four rakers, 12 vertical supports, eight diagonal braces and two sloped side rails. Geometry is 38 editable solids (~380 polygons before any generator-specific details).
- Omitted: individual seat divisions, guardrail balusters, stairs, roof, footplates, crossways and spectators. First-pass scenery blockout. No automated BSP/LOD; inspect ordering and in-game visibility.
- Scaffolding simplified to four planar frames spaced 12 ft along the stand. Posts and diagonals are rectangular low-poly solid sections, not cylinders.
- Colors: indices **30** (framework and rail) and **32** (bench decking), from the *shared* blue-gray 25–34 range of gamepal/sunny palettes documented at https://skchow.com/indy/palette/ . **RGB swatch values have not yet been independently verified; hues are provisional**, and should be audited against the actual target SUNNY.PCX before importing into a finished track. These do not use track-customizable indices 176–254.
- The stand's face winding, BSP/LOD and real-world geometry need manual in-game checking. No original game asset overwritten.
