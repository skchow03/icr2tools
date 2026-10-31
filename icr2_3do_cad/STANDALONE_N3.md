## Opening a standalone .3D file

**A preexisting binary .3DO is no longer required.** Use **File → Open…**
and select a Papyrus/N3 \`.3D\` text file, or **File → Open standalone N3 .3D…**.
The editor compiles the text in memory, validates the 3DO record tree, and
opens the result in the existing vertex/polygon editor and viewport.
**Save Copy** produces a new binary \`.3do\`. This operation never overwrites
your source \`.3D\` file. Reexporting unchanged text returns it byte-for-byte,
including comments and pointer names. Reexporting after changes emits a
canonical N3 file retaining named record labels and attached comments where
possible; inline expressions may become separate declarations.

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

The original binary-overlay import remains available when an existing
\`.3do\` is open; standalone import is the recommended path for new work.
