# REND32A Multi-Car: binary patch technical reference

This document describes **what the published `rend32a_multicar.py` patcher
changes in an original REND32A `CART.EXE`**, why the changes are necessary,
and how its injected x86 code works. It is for modders, reverse engineers,
and anyone reviewing or reproducing the patch. For installation instructions
see the [README](README.md).

**Validation status:** The developer has reported that the generated
REND32A Multi-Car executable works in the game. The earlier FOUR V2 + C2
four-chassis/wheel case was also observed working in-game. This is not an
exhaustive validation of arbitrary carsets, all camera modes, replays,
damage, or very large chassis lists. Address maps and patch bytes below are
for one exact executable revision, not generic ICR2 offsets.

## 1. The problem and the three fixes

The original renderer sometimes replaces a car's individual chassis pointer
with a shared/default chassis pointer. Loading different driver wrapper
`.3do` files therefore does not by itself guarantee different body shapes.
Models outside the stock Roadcar/Indycar set also require their resources
to be loaded into the Rendition resource context, including texture data.
Finally, the original wheel update path uses pointers associated with a
shared/default chassis, so wheels on nondefault chassis can have incorrect
rotation or tire appearances.

The patch combines these changes:

1. **Preserve each car's chassis reference:** NOP the instruction that
   overwrites it.
2. **Preload additional chassis resources:** redirect the existing Roadcar
   loader call to a trampoline that loads Roadcar first, then the additional
   `.3do` model names selected when the executable is patched.
3. **Update wheel attachments per draw:** divert two existing tire-selection
   calls to adapters that preserve the stock selector, find the chassis
   currently attached to the car being rendered, and set wheel rotation and
   appearance fields immediately before drawing.

The patch **does not** assign chassis to drivers, modify carset data, create
3DO files, or install a live-memory hook. Driver-to-chassis assignments and
all requisite resources must already exist in the carset. This is a
permanent *output-file* patch made from the user's own unmodified executable.

## 2. Supported binary, hashes, and address conventions

| Item | Value |
| --- | --- |
| Input | Original unmodified REND32A `CART.EXE` |
| Input size | `1,109,095` bytes |
| Input SHA-256 | `e22effeb75105a3155212eb25d88b2e2cd127d521b72d0fa122adbd32e7a721c` |
| Rebuilt FOUR V2 + wheel C2 baseline SHA-256 | `cba955eab5ed03a83bebf9fa0553dca8b871e6d6405e6b5383c241a310b85be0` |
| Example final SHA-256 (additional `irl` and `panoz`) | `6105d39d94862eb5483f64ba27f7c1e4a8e6ac029c935c4c9631ebd5a1ecdd3c` |
| Executable format | DOS/32A **LE** (Linear Executable), x86 32-bit |
| LE header start | raw `0x6E68` |
| Code object 1 file start | raw `0x4BE20` |
| Code object 1 guest base | `0x10000` |
| Existing mapped code pages | `0x9C` = 156 pages, 4096 bytes each |

**Two address systems are used.** A *raw/file offset* locates bytes in
`CART.EXE` on disk. A *guest address* is the REND32A code address used by a
disassembler or by executing DOSBox guest code. For this particular
executable's code object 1, the translation is:

```text
raw file offset = guest code address + 0x3BE20
guest code address = raw file offset - 0x3BE20
```

This conversion applies to the verified code-object mapping, **not** to
the LE header, arbitrary data objects, or arbitrary REND32A revisions.
The displacements in the near `CALL` instructions below are relative and
little-endian, not absolute addresses. All four-byte LE header fields are
little-endian as well.

## 3. Full top-level patch map

The single-file Python patcher first recreates the known FOUR V2 + C2
baseline, then applies the season-specific preload. The following table
shows the **original input** and the resulting **Multi-Car executable**.
“Original” is the *unmodified* CART.EXE; the C2 intermediate is shown
separately where needed.

| Raw file offset | Guest address | Original bytes/value | Final bytes/value | Purpose |
| --- | --- | --- | --- | --- |
| `0x6F2C` (4 bytes) | LE header, not code | `01 B3 09 00` = `0x9B301` | `00 B8 09 00` = `0x9B800` for the default list; may increase | Extend code-object virtual size to include the injected regions |
| `0x6F34` (4 bytes) | LE header, not code | `45 20 00 00` = `0x2045` | `47 20 00 00` = `0x2047` | Allow the C2 diagnostic trace storage to be written; broadens code-object permissions |
| `0x80ACF` | `0x44CAF` | `89 02` | `90 90` | Disable `mov [edx], eax`, which overwrites the individual chassis pointer |
| `0x50970` | `0x14B50` | `E8 97 7A 05 00` | `E8 CB 6B 09 00` | Redirect original Roadcar preload call to new loader at guest `0xAB720` |
| `0xE7160–0xE71AB` | `0xAB340–0xAB38B` | zero-filled | 76-byte FOUR V2 preload code | Old fixed `irl`/`panoz` preloader stays in the binary but is **bypassed** by the new call |
| `0x56E07` | `0x1AFE7` | `E8 A4 C6 02 00` | `E8 A4 03 09 00` | Main renderer: `call 0x47690` becomes `call 0xAB390` |
| `0x60052` | `0x24232` | `E8 59 34 02 00` | `E8 A9 71 08 00` | Direct renderer: `call 0x47690` becomes `call 0xAB3E0` |
| `0xE71B0–0xE7537` | `0xAB390–0xAB717` | zero-filled | C2 wheel adapters, common wheel updater and trace storage | Original per-draw wheel functionality is wrapped and extended |
| `0xE726C` | `0xAB44C` | zero-filled in *unmodified* input | `EB 26 90 90 90 90` | C2's six-byte adjustment inside the injected helper; explained below |
| `0xE7500` | `0xAB6E0` | zero-filled | `49 43 57 32 02 00 00 00 ...` | `ICW2` version-2 diagnostics/counters, 56 bytes |
| `0xE7540` onward | `0xAB720` onward | zero-filled | New position-independent loader plus variable name table | Preload requested chassis names in 16-byte slots |

The preload call at raw `0x50970` had **another** value in the C2
intermediate: `E8 EB 67 09 00`, calling the fixed FOUR V2 routine at raw
`0xE7160`. The final stage redirects it again to `0xE7540`; it does not
delete or rewrite the old injected routine.

The C2 adjustment at `0xE726C` is often misunderstood: immediately
**before** that adjustment, in the intermediate wheel Build C, the six bytes
were `8B 85 70 92 F6 FF` (`mov eax, [ebp-0x96D90]`). C2 replaces them
with `EB 26 90 90 90 90` (`jmp short +0x26` and four NOPs), jumping
to guest `0xAB474`. The unmodified original had only zeros at this location;
the comparison is **Build C → C2**, not original → C2. This bypasses
the special exclusion checks for stock Roadcar and Indycar roots, allowing
the same validated per-car wheel routine to run on those chassis too.

For the standard `irl`/`panoz` example, the new preload is 96 bytes
(64 bytes code/alignment plus two 16-byte filenames), and the LE virtual
size remains `0x9B800`. The C2 baseline differs from the original in
**894 byte positions**; the season-specific stage changes **72 additional
byte positions relative to C2** for that default example (964 positions
differ between the original and final files). Those numbers describe
actual differing byte positions, not the sizes of reserved cave regions.

## 4. Preserving chassis geometry

At raw `0x80ACF` / guest `0x44CAF`:

```asm
; Original (2 bytes: 89 02)
mov [edx], eax

; Patched (2 bytes: 90 90)
nop
nop
```

This suppresses a write that otherwise replaces an individual car's
attached chassis reference with the shared/default reference. The engine's
other chassis-loading and rendering operations are retained. The
neighboring original instruction at raw `0x56A80` (`89 10`) is **not**
changed by the FOUR V2 chassis-preservation step.

## 5. Model-resource preload trampoline

The original `CALL` at raw `0x50970` / guest `0x14B50` loads Roadcar
using the game's existing 3DO loader, whose original entry point is raw
`0xA840C` / guest `0x6C5EC`. The final `CALL` targets the new trampoline
at raw `0xE7540` / guest `0xAB720`. In high-level x86 pseudocode:

```asm
call original_3do_loader     ; preserve the original Roadcar load
pushad                       ; save the original loader result/registers
sub esp, 16                  ; working space, matching older trampoline
call get_pc                  ; position-independent address discovery
get_pc:
pop esi
lea esi, [esi + table_delta] ; pointer to 16-byte filename slots
mov edi, name_count
test edi, edi
jz done
load_next:
    push esi
    push edi
    mov eax, esi             ; address of this "name.3do" string
    call original_3do_loader
    pop edi
    pop esi
    add esi, 16
    dec edi
    jnz load_next
done:
add esp, 16
popad                        ; restore original Roadcar loader result
ret                          ; resume game after original CALL
; 16-byte aligned:
; "irl.3do\\0" padded to 16 bytes
; "panoz.3do\\0" padded to 16 bytes
```

The actual writer `emit_payload()` emits raw x86 instructions without
an assembler and fixes relative `CALL` and short branch displacements.
It stores one null-terminated `name.3do` string per **16-byte slot**.
Names are ASCII, DOS 8.3-compatible, case-normalized and deduplicated;
the stock `roadcar` and `indycar` loads are not redundantly listed.

**Preloading is not per-driver selection.** The carset's `cars.3do` and
driver wrappers determine which chassis a car requests. Preloading makes
additional model resources available when those references are resolved.
When `--carset-dir` is supplied, the patcher discovers these references
through the supported F16 `SUPEROBJ` → F15 `DYNAMIC` driver entry and
F04 `MATERIAL` → F14 `RECOLOR` external model reference. It fails on
unsupported structure rather than guessing.

For the verified LE layout, the injected names can occupy no more than
the remaining allocated code pages. The current limit is **138 extra
distinct names**, a *patch-space limit*, not a tested 138-chassis game
capacity; normal carsets have at most 33 driver entries.

## 6. The C2 wheel-rendering adapters and common helper

The original renderer calls the stock tire selector at guest
`0x47690` in two places. C2 keeps its existing effects and adds a
per-car update just before drawing. It does **not** permanently repoint
the game's global front/rear wheel caches.

### Main renderer adapter: guest `0xAB390`

1. Call the existing `0x47690` tire selector.
2. Save flags and general registers (`pushfd`, `pushad`).
3. Find the car index through the render/model record, using its
   `+0x74` index field; invalid pointers are skipped.
4. Obtain wheel phase from saved EBP and steering/orientation from the
   original stack.
5. Invoke the shared wheel update routine with stream ID 0.
6. Restore registers/flags and return to the original renderer.

### Direct renderer adapter: guest `0xAB3E0`

1. Call the existing `0x47690` tire selector.
2. Save flags/registers.
3. Obtain the car index from `[EDI+0x74]`, wheel phase from
   `[ESI+0x24]`, and steering/orientation from `[ESI+0x28]`.
4. Invoke the shared updater with stream ID 1.
5. Restore registers/flags and return.

### Shared wheel update: what is read and written

The helper uses an existing relocated instruction operand to find the
per-car chassis-pointer table (identified in the original analysis as the
guest `0x3C1C8` table), indexes it by car 0–32, and follows the selected
car's *attached* chassis pointer. It requires:

- a valid, non-null chassis/root pointer of type `0x10` (F16
  `SUPEROBJ` in the game's in-memory representation);
- at least four children;
- child slots **0–3** each pointing to a type `0x0F` (F15
  `DYNAMIC`) wheel attachment.

Invalid car indices and incompatible structures are skipped rather than
written through blindly. The selected/player car uses a separate
renderer/hierarchy and does not necessarily have an applicable entry in
this table; the stock selected-car path remains responsible.

For each validated wheel attachment, the helper **writes**:

| In-memory DYNAMIC offset | Field | Value |
| --- | --- | --- |
| `+0x10` | Z rotation | Steering/orientation for front wheels, fixed zero/half-turn values at rear |
| `+0x14` | Y rotation | Current car's spin/rotation phase, negated for opposite side |
| `+0x18` | X rotation | `0` |
| `+0x1C` | Wheel appearance/model reference | The current front or rear resource chosen by the original tire selector |

The exact per-wheel rotations use the game's wrapping 32-bit angle space.
Let `T` be steering/orientation and `P` the wheel phase:

| Child index | Wheel | Z | Y | X |
| --- | --- | --- | --- | --- |
| 0 | front | `T` | `P` | 0 |
| 1 | front | `T XOR 0x80000000` | `-P` | 0 |
| 2 | rear | 0 | `P` | 0 |
| 3 | rear | `0x80000000` | `-P` | 0 |

Front children 0/1 receive the front tire reference; rear children 2/3
receive the rear reference. Pointer operands come from original,
loader-relocated game instructions, rather than hard-coded live Windows
host addresses. Each call updates only the wheel attachments of the
chassis being drawn.

**Why per draw?** The 3DO loader can cache a chassis hierarchy under a
model name, so several cars using the same 3DO may share a model-node
tree. Writing wheel rotation just once during car initialization would
not produce independent animation. The C2 hook applies the active car's
phase and appearance **immediately before its draw**, allowing mixed
chassis and tire manufacturers.

### C2 diagnostics at guest `0xAB6E0` (raw `0xE7500`)

The C2 helper contains a **56-byte trace buffer** initialized in the
patched executable. It is writable in the running game and can be
inspected through memory diagnostics; it is not an external data file.

| Buffer byte offset | Meaning |
| --- | --- |
| `+0x00` | ASCII `ICW2` |
| `+0x04` | Version `2` (`uint32`) |
| `+0x08`, `+0x0C` | Main/direct adapter hit counts |
| `+0x10`, `+0x14` | Main/direct completed wheel-update counts |
| `+0x18`, `+0x1C` | Main/direct invalid-pointer/structure counts |
| `+0x20` | Legacy single-car-filter target index (normally unused in C2) |
| `+0x24` | Last successfully updated car index |
| `+0x28` | Last validated chassis root pointer |
| `+0x2C` | Most recent car index examined |
| `+0x30`, `+0x34` | Original Roadcar/Indycar skip counters from the intermediate helper; their exclusion branch is bypassed in C2 |

The trace buffer is why the LE object flags change to make the code
object writable. Its counters are diagnostics, **not** proof that every
wheel renders correctly in every context.

## 7. LE layout, code caves, and integrity safeguards

The original object-1 virtual size at raw `0x6F2C` is `0x9B301`, too
small to expose the injected cave consistently. FOUR V2 extended it to
`0x9B500`; C2 further extended it to `0x9B800`. The configurable loader
recomputes the required end of its payload, aligns it to 16 bytes and
uses the larger of the C2 size and the new required size.

- The code object starts at guest `0x10000` and uses the same **156
  existing 4 KiB pages**. No new LE pages or relocation records are
  inserted.
- `0x2045 → 0x2047` at the object's flags field (`0x6F34`) allows
  guest writes to the C2 trace buffer. **This grants writability to
  the code object more broadly**, not just those 56 bytes.
- The new loader is placed in formerly zero-filled mapped space after
  the C2 helper at raw `0xE7540`. Its `call/pop` technique avoids new
  LE relocations.
- The patch checks that the output does not exceed mapped pages or
  overlap the next LE object base (`0xB0000`).

The published script encodes **only replacement-byte runs**, not a
copy of `CART.EXE`. They are Base85-encoded and zlib-compressed in
`_BASELINE_DELTA`. Each decoded record is:

```text
uint32_le file_offset
uint16_le replacement_length
byte[replacement_length] new_bytes
```

The builder first verifies the original executable's *size and SHA-256*,
applies the non-overlapping replacement runs to reconstruct FOUR V2+C2,
and verifies the reconstructed **C2 SHA-256**. It then checks the C2
LE layout, existing hook signatures, geometry NOP, wheel-helper
signature, empty new code cave and lack of conflicting relocation
fixups before adding the variable preload.

At the season-specific stage, the permitted changed regions relative
to C2 are exactly (1) the new preload payload at `0xE7540` onward,
(2) the five-byte Roadcar loader call at `0x50970`, and
(3) the four-byte virtual-size field at `0x6F2C` when expansion is
needed. It explicitly checks that the old FOUR V2 preload,
C2 wheel routines, geometry NOP, wheel call sites, and flags
remain untouched. The final file size does not change.

The script will **not** overwrite the input executable and by default
will not overwrite an existing output. It only accepts one known
REND32A original SHA-256. Do not transplant these offsets to another
game version just because its file format is also LE.

## 8. Reproducibility, boundaries, and historical source

The current single-file builder deliberately avoids an external
assembler. For independent auditing, the original, human-readable
assembly and intermediate builders are retained in Git history at
the commit **before** the single-file consolidation:

- [`wheel_patch_bc.S`: full C2 wheel adapter and update assembly](https://github.com/skchow03/icr2tools/blob/2b064bcb1e619df222cc1a4624676f9b79d174d9/icr2multicar_rend32a/wheel_patch_bc.S)
- [`build_rend32a_preload_v2.py`: original four-model preload builder](https://github.com/skchow03/icr2tools/blob/2b064bcb1e619df222cc1a4624676f9b79d174d9/icr2multicar_rend32a/build_rend32a_preload_v2.py)
- [`build_wheel_BC.py` and `build_C2.py`: wheel helper construction and six-byte C2 change](https://github.com/skchow03/icr2tools/tree/2b064bcb1e619df222cc1a4624676f9b79d174d9/icr2multicar_rend32a)

A byte-for-byte reconstruction of the verified C2 baseline has been
performed against the original user's 1,109,095-byte executable. The
default `irl`/`panoz` finished binary matches the older configurable
patcher output exactly (hash listed above).

The reported live success is encouraging, but the following remain
useful community test cases: different carsets with 5+ distinct chassis,
two cars sharing one 3DO at different speeds, Firestone/Goodyear
appearances, selected-car/TV/replay cameras, pits, damage, track reloads
and long races. The 138-name binary-capacity bound is **not** an
assurance of practical texture or memory capacity.

Distribute the **patcher source**, not modified proprietary
`CART.EXE`, 3DO files, or copyrighted assets.
