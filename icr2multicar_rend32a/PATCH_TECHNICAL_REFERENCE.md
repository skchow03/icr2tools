# REND32A Multi-Car — technical reference

This document describes exactly how `rend32a_multicar.py` modifies the
**original, unmodified Rendition IndyCar Racing II `CART.EXE`**. It is intended
for programmers, modders and reverse engineers who want to understand or audit
the patch. Installation and command-line instructions are in the [README](README.md).

The developer reports successful testing in the game. This does not establish
compatibility with every carset, chassis format, camera, replay or race state.

## 1. What the patch does

Stock REND32A loads and displays Roadcar and Indycar geometry through several
shared resources. Merely substituting different `.3do` filenames in a carset
is not enough: the game can replace an individual car's chassis pointer with
the shared model, additional models may not yet be loaded, and the wheel
animation path can update the wrong chassis's wheel attachments.

The patched executable addresses all three problems:

1. **Keep the car's chosen chassis.** Remove a write that replaces an
   individual chassis reference with the shared/default pointer.
2. **Load additional chassis models.** Run the game's existing 3DO loader
   on user-selected model names, so those resources are available before
   cars are rendered.
3. **Update each car's wheels just before drawing.** Hook two rendering
   call sites, preserve the game's original tire-selection logic, and
   update rotation and front/rear wheel appearance on the chassis currently
   used by the car being drawn.

This is an **on-disk EXE patch**, not a runtime injector. The tool does not
edit `cars.3do`, driver wrappers, chassis resources, or texture files.
The carset still determines which model each driver uses.

## 2. Supported input and address conventions

The patcher accepts either the stock executable or one **exact, known modified variant**. Other hashes are rejected:

| Property | Required value |
| --- | --- |
| Executable | Original REND32A `CART.EXE` |
| Size | `1,109,095` bytes |
| Original stock SHA-256 | `e22effeb75105a3155212eb25d88b2e2cd127d521b72d0fa122adbd32e7a721c` |
| Recognized alternate SHA-256 | `14385142e4f0b99541f018c1f20eccd854fd17103da0dfddd81472520f9c3360` |
| Format | DOS/32A Linear Executable (LE), 32-bit x86 |
| LE header file offset | `0x6E68` |
| Code object 1 file offset | `0x4BE20` |
| Code object 1 guest address | `0x10000` |
| Existing code object pages | `0x9C` (156 × 4096 bytes) |

Two kinds of addresses appear throughout this document:

- **Raw/file offset:** the location of bytes in the executable on disk.
- **Guest address:** the location of the instruction after the LE loader
  maps the code object into the emulated DOS address space.

For code object 1 in this *specific* executable:

```text
guest_address = raw_file_offset - 0x3BE20
raw_file_offset = guest_address + 0x3BE20
```

For example, the instruction at raw `0x80ACF` executes at guest `0x44CAF`.
Do **not** apply this translation to the LE header, other objects, or
different executable versions.

## 3. Stock-to-patched binary map

The entries in this table compare **the stock `CART.EXE` directly with the
final generated `CART_MULTICAR.EXE`**. For the recognized variant, all its
pre-existing changed bytes are **preserved on top of these modifications**;
the core hook offsets and original bytes at those hooks are identical.
There are no prerequisite patched executables or assembly components.

| Raw file offset | Guest address | Stock bytes/value | Patched bytes/value | Result |
| --- | --- | --- | --- | --- |
| `0x6F2C` (4 bytes) | LE header | `01 B3 09 00` (virtual size `0x9B301`) | At least `00 B8 09 00` (`0x9B800`); larger lists can extend it | Map injected code and filename table |
| `0x6F34` (4 bytes) | LE header | `45 20 00 00` (flags `0x2045`) | `47 20 00 00` (`0x2047`) | Permit writes to the wheel diagnostics buffer; code-object permission is broadened |
| `0x80ACF` | `0x44CAF` | `89 02` | `90 90` | Disable the chassis-pointer overwrite |
| `0x50970` | `0x14B50` | `E8 97 7A 05 00` | `E8 CB 6B 09 00` | Redirect the existing 3DO load call to the new model preloader |
| `0x56E07` | `0x1AFE7` | `E8 A4 C6 02 00` | `E8 A4 03 09 00` | Redirect the main renderer tire-selection call |
| `0x60052` | `0x24232` | `E8 59 34 02 00` | `E8 A9 71 08 00` | Redirect the direct renderer tire-selection call |
| `0xE71B0–0xE7537` | `0xAB390–0xAB717` | Zero-filled space | Wheel adapters, wheel update routine and diagnostics | Perform per-car wheel/tire updates |
| `0xE7500` | `0xAB6E0` | Zero-filled space | `49 43 57 32 02 00 00 00 ...` | Initialize the 56-byte `ICW2` diagnostics buffer |
| `0xE7540` onward | `0xAB720` onward | Zero-filled space | New loader routine plus filename table | Preload additional chassis files |

There is also an **unused 76-byte routine** in `0xE7160–0xE71AB`
(guest `0xAB340–0xAB38B`), written into otherwise empty code space.
The final game call at `0x50970` targets `0xE7540` instead, so this
extra routine is **not the one executed**. It is retained in the
preverified embedded patch bytes and is not needed to understand the
active code path.

The six bytes at raw `0xE726C` (guest `0xAB44C`) are
`EB 26 90 90 90 90` in the final wheel helper: a short jump and four
NOPs. They skip a model-type exclusion path so the wheel updater also
handles the stock Roadcar and Indycar chassis. The stock EXE had
zero-filled space at this location.

**The executable file length stays unchanged.** The additional routines
occupy existing, previously unused file space that the patch makes
visible to the LE loader.

## 4. Chassis-pointer preservation

**Raw `0x80ACF` / guest `0x44CAF`**

```asm
; Stock: 89 02
mov [edx], eax

; Patched: 90 90
nop
nop
```

In the affected renderer/model setup path, `EAX` supplies a shared
chassis pointer and `EDX` addresses the car-specific pointer slot.
Suppressing the write allows the existing per-driver chassis reference
to survive. It does not rewrite the carset or insert new model-selection
rules.

A separate original instruction at raw `0x56A80` (`89 10`) is **not**
modified by this geometry fix.

## 5. Preloading additional chassis models

**Call site:** raw `0x50970` / guest `0x14B50`.

The stock game calls an existing loader for Roadcar. The patch replaces
that five-byte relative `CALL` with one targeting raw `0xE7540`,
guest `0xAB720`. The game's original 3DO loader remains at raw
`0xA840C` / guest `0x6C5EC`.

The new loader performs the original Roadcar load first, then feeds
each requested chassis filename to that same game loader. In
annotated x86-style pseudocode:

```asm
call original_3do_loader     ; do what the stock call did
pushad                       ; preserve original returned register values
sub esp, 16                  ; temporary working space
call get_pc                  ; find table independent of relocation
get_pc:
pop esi
lea esi, [esi + table_delta] ; first 16-byte filename slot
mov edi, name_count
test edi, edi
jz done
next_name:
    push esi
    push edi
    mov eax, esi             ; pointer to ASCII "name.3do"
    call original_3do_loader
    pop edi
    pop esi
    add esi, 16
    dec edi
    jnz next_name
done:
add esp, 16
popad
ret                          ; back to the original caller
; 16-byte aligned filename table follows:
; "irl.3do\0"   [padding to 16 bytes]
; "panoz.3do\0" [padding to 16 bytes]
```

The Python patcher writes these opcodes directly, computes the relative
`CALL` and short-branch displacements, and uses a position-independent
`call/pop` technique instead of introducing new LE relocation records.
The fixed program code and alignment use 64 bytes, followed by
**16 bytes per additional chassis name**.

Names are ASCII 8.3-compatible basenames (1–8 characters before
`.3do`), normalized to lowercase and deduplicated. The already
available `roadcar` and `indycar` model names are excluded from the
additional list.

**What determines the chassis of a particular driver?** The existing
carset. The patcher optionally reads `cars.3do` and the driver `.3do`
wrappers to discover additional resource names. The supported hierarchy
is F16 `SUPEROBJ` → F15 `DYNAMIC` for driver entries and
F04 `MATERIAL` → F14 `RECOLOR` → external chassis reference inside each
driver wrapper. The preloader loads those resources, but it never
reassigns drivers to models.

## 6. Per-car wheel and tire rendering

Stock REND32A calls its tire-selection routine at guest `0x47690` from
two rendering paths. The patch retains that routine and hooks each
call so the active car's wheel attachments are updated immediately
before the renderer draws the model.

### 6.1 Main renderer hook

- **File offset:** `0x56E07`
- **Guest call site:** `0x1AFE7`
- **Stock call target:** `0x47690`
- **New call target:** `0xAB390` (file `0xE71B0`)

The adapter calls the original tire selector, then saves flags and
general registers (`pushfd` / `pushad`). It obtains the current car
index through the render/model record's `+0x74` field, retrieves wheel
spin from the saved EBP context and steering/orientation from the
original stack, and calls the common updater with stream ID 0. It
restores the registers and flags before returning to the stock
renderer.

### 6.2 Direct renderer hook

- **File offset:** `0x60052`
- **Guest call site:** `0x24232`
- **Stock call target:** `0x47690`
- **New call target:** `0xAB3E0` (file `0xE7200`)

This adapter also runs the stock tire selector first. It reads the
car index from `[EDI+0x74]`, wheel spin from `[ESI+0x24]`, and
steering/orientation from `[ESI+0x28]`, then calls the common updater
with stream ID 1. General registers and flags are preserved.

### 6.3 Common updater: input validation and pointer resolution

The helper follows the game's existing per-car chassis reference,
rather than forcibly using a shared chassis. The per-car table was
identified at guest `0x3C1C8`; the code reads the relevant pointer
operands from **already relocated game instructions**, including:

| Guest address | Role |
| --- | --- |
| `0x44C9E` | Operand identifying the per-car chassis slot table |
| `0x476B1` | Operand identifying the original front wheel appearance source |
| `0x476C3` | Operand identifying the original rear wheel appearance source |

These are **addresses read by the new helper**, not locations where
the patch overwrites stock instructions. The original tire selector
still determines the front and rear wheel resources.

The helper accepts car indices **0–32** and verifies the attached
chassis is non-null, has F16 type `0x10` and has at least four children.
Wheel child indices 0–3 must each be F15 `DYNAMIC` nodes of type
`0x0F`. Unexpected pointers or model structures are skipped rather
than blindly written through. The selected/player car can follow a
separate rendering hierarchy, which is not replaced by this helper.

### 6.4 Exact per-wheel fields written

For each validated `DYNAMIC` wheel attachment the patch writes:

| Offset within wheel node | Value/function |
| --- | --- |
| `+0x10` | Z rotation (steering/orientation or fixed rear orientation) |
| `+0x14` | Y rotation (wheel spin, with opposite sign on the other side) |
| `+0x18` | X rotation, set to 0 |
| `+0x1C` | Front or rear wheel appearance/model reference returned by stock selection |

Let `T` be the current car's steering/orientation angle and `P` its
wheel spin phase. Angles use the game's wrapping 32-bit representation.

| Child | Z rotation | Y rotation | X | Appearance |
| --- | --- | --- | --- | --- |
| 0 — front | `T` | `P` | 0 | Front |
| 1 — front | `T XOR 0x80000000` | `-P` | 0 | Front |
| 2 — rear | 0 | `P` | 0 | Rear |
| 3 — rear | `0x80000000` | `-P` | 0 | Rear |

These writes target the *current car's attached chassis wheel nodes*,
not the stock global wheel resource pointers.

**Why update at draw time?** Cars that reference the same chassis
filename may share an in-memory 3DO hierarchy. A single
initialization-time wheel assignment cannot represent several cars
spinning at different speeds. Updating the active car's wheel children
immediately before rendering lets the shared geometry show
car-specific wheel movement and tire appearances.

### 6.5 Diagnostic buffer

**Raw `0xE7500` / guest `0xAB6E0`** is a 56-byte diagnostic record
within the injected helper. Its first eight bytes are
`49 43 57 32 02 00 00 00` (ASCII `ICW2`, version 2).

| Offset | Field |
| --- | --- |
| `+0x00` | Signature `ICW2` |
| `+0x04` | Version (32-bit, value `2`) |
| `+0x08` | Main-renderer adapter hit count |
| `+0x0C` | Direct-renderer adapter hit count |
| `+0x10` | Main-renderer successful wheel updates |
| `+0x14` | Direct-renderer successful wheel updates |
| `+0x18` | Main-renderer invalid-pointer/structure skips |
| `+0x1C` | Direct-renderer invalid-pointer/structure skips |
| `+0x20` | Reserved car-filter index field; not active in the current updater |
| `+0x24` | Last successfully updated car index |
| `+0x28` | Last validated chassis root pointer |
| `+0x2C` | Most recently examined car index |
| `+0x30` / `+0x34` | Inactive stock-model exclusion counters; the current helper bypasses that exclusion |

The trace is **in game memory** and does not create a log file.
It can assist diagnostics but does not independently prove correct
visible animations in every camera and carset.

## 7. LE header, code space and file integrity

The injected routines occupy mapped unused bytes in code object 1.
The input object's virtual size is `0x9B301`. The patch increases it
to at least `0x9B800` and, if a longer model-name table needs more
room, aligns the resulting size upward to 16 bytes. The patch checks
that the mapped virtual size stays within the existing **156 pages**,
and that code does not overlap the following object base at `0xB0000`.

The LE code-object flags change from **`0x2045` to `0x2047`**
to permit writes to the in-memory `ICW2` counters. This changes
permissions for the entire code object, not just the trace record;
that is a relevant safety/compatibility tradeoff.

No page count or relocation records are added. The new preloader
checks its allocated area for zeros and that no existing LE fixups
overlap. The final executable stays exactly the same length.

### How the single-file Python patcher constructs the output

The source ships **replacement-byte runs**, compressed using zlib and
encoded with Base85, in `_CORE_PATCH_DELTA`. It does **not** embed an entire
game executable. Each decoded replacement run is:

```text
uint32_le raw_file_offset
uint16_le replacement_length
byte[replacement_length] replacement_bytes
```

The patcher:

1. Verifies the input by **size and exact SHA-256**, accepting only the
   two documented variants. For the alternate, verifies its nine known
   edit runs and restores the corresponding stock bytes **in memory**,
   checking the resulting original SHA-256.
2. Applies the bounded, non-overlapping replacement runs for chassis
   preservation, wheel hooks/helper and the necessary LE changes.
3. Checks a second, fixed SHA-256 digest of that common patched state,
   rejecting damaged patch data or an unexpected reconstruction.
4. Confirms the LE object layout, expected hook instruction signatures,
   chassis NOP, wheel helper signature, empty filename-preload area
   and lack of relocation overlap.
5. Inserts the user-selected preloader and filename table; redirects
   the original Roadcar call; extends virtual size if required.
6. Checks that **only** those three additional regions were changed.
   For the recognized alternate, it then reapplies its nine original edit
   runs (31 actual differing bytes) **only after checking for conflicts**
   with Multi-Car's changes. The resulting output hash is verified before
   reporting success; the input executable is never overwritten.

The internal digest used for step 3 is
`cba955eab5ed03a83bebf9fa0553dca8b871e6d6405e6b5383c241a310b85be0`.
It is an **integrity checkpoint**, not a separate file that users
need to find, download or build.

With the default extra names `irl` and `panoz`, the resulting executable
has SHA-256:
`6105d39d94862eb5483f64ba27f7c1e4a8e6ac029c935c4c9631ebd5a1ecdd3c`.

### Recognized modified CART.EXE (additional input)

The alternate REND32A binary has the same 1,109,095-byte length, LE
layout, chassis overwrite instruction, and two original wheel call
sites as the stock executable. Its SHA-256 is
`14385142e4f0b99541f018c1f20eccd854fd17103da0dfddd81472520f9c3360`.

It differs from stock by **31 bytes across ten contiguous difference
regions**, covering nine complete instruction/data ranges listed below.
The program does not replace these regions; it retains them in the
alternate Multi-Car output.

| Raw offset | Original → alternate | What changes |
| --- | --- | --- |
| `0x61C26`, `0x61F74`, `0xAE67E`, `0xF5FC0` | `0x0027AC40` → `0x04F58800` | Four copies of a numeric constant: 2,600,000 → 83,200,000 (×32) |
| `0x6A3C7` | `0x9140` → `0x4320` | Immediate arithmetic constant, 37,184 → 17,184 |
| `0x6BED8` | `0F B6 15 78 CB 0E 00` → `8B 14 95 74 CB 03 00` | Changes a byte read from fixed address into a 32-bit indexed-table read |
| `0x79244` | `0x0000152C` → `0xFFFFEAD4` | Signed immediate changes from +5,420 to −5,420 |
| `0x79252` | `0x1A60` → `0x2230` | Immediate changes from 6,752 to 8,752 |
| `0xABC9A` | `0x444B` → `0xCCE1` | High 16 bits of a 32-bit initialization value change |

These are not merely metadata. The changed 32-fold constant is
**consistent with** an expanded game-memory allocation or limit,
but this exact executable's provenance and the intended purpose
of every other difference have not been independently established.

**Safety findings:** Compared with the generated default Multi-Car
executable, **none** of the 31 alternate bytes overlaps an overwritten
stock instruction, injected routine, or LE header patch. The patcher
normalizes the alternate to the pinned stock checksum in memory,
applies its existing verified binary transformation, then restores
the alternate bytes to the output, refusing a byte conflict. For
the default `irl`/`panoz` list the expected alternate-output
SHA-256 is
`f19aeca5a4a34a544961ae86ec575c7d7d3b17dbebf0785b061664aea1dd84d2`.

**This verifies binary preservation, not runtime behavior.**
The alternate contains different executable instructions and
constants that may interact with other rendering or resource
paths. The combined output still requires a live REND32A test
in a disposable game installation.

## 8. Limitations and community testing

- **Exact-version patch.** These offsets and hook signatures were verified
  against both specified SHA-256 inputs. Unknown DOS, WINDY or patched
  EXEs are rejected; the offsets are not portable.
- **Carset requirements.** The model files, textures and driver wrapper
  references must already exist. The patcher does not generate them.
- **Model structure.** The wheel helper assumes F16 chassis roots with
  wheel children 0–3 represented as F15 `DYNAMIC` nodes. Other layouts
  are skipped or may not render as intended.
- **Model count.** The reserved filename space accommodates at most
  **138 additional distinct basenames**. This is a file-layout bound,
  not evidence that the game can load 138 unique chassis resources.
  Normal carsets have up to 33 driver entries.
- **Not fully regression-tested.** In-game operation has been reported
  successful, but different carsets, shared 3DO models, mixed tire
  appearances, unusual cameras, damage, replay, pit stops, track reloads
  and extended races merit further testing.

Distribute the source patcher rather than proprietary patched
`CART.EXE` binaries or copyrighted 3DO assets.
