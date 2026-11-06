## Opening a standalone .3D file

A preexisting binary .3DO is not required. Choose **File → Open Model…** and
select Papyrus/N3 `.3D` text. 3DO CAD compiles and previews the source and
makes it editable in the .3D Source pane. **Save .3D Source As…** saves the
source document; **Export Compiled 3DO…** validates and writes a separate
binary model. Source names and comments are retained in the text document but
not stored in the compiled binary.

Supported starting constructs include named vertex declarations, \`POLY\`,
\`POLY [T]\`, \`LINE\`, \`LIST\`, \`FACE\`, \`FACE2\`, \`BSPF\`, \`BSPA\`,
\`BSP2\`, \`BSPN\`, \`MATERIAL\`, \`DYNAMIC\`, \`SUPEROBJ\`,
\`SWITCH DISTANCE\`, \`DYNO\`, \`DATA\`, \`RECOLOR\`,
\`SRB\`/\`PMP2\`, NIL and nested command expressions. Text labels
and \`% comments\` are not stored in binary, so retain the source text.

This is a compiler for a **tested subset** of N3, not a claim of complete
Papyrus or Noorok 3d23do source compatibility. Unsupported grammar,
invalid pointer names, missing assets, malformed BSP branches and
out-of-range numbers fail explicitly. An in-game visual check is still
essential for complex BSP/material arrangements.

The current editor recompiles source rather than offering an in-place binary
overlay import. Keep your original files and test compiled models in-game.
