# WINDY101 Multi-Car — technical reference

This document explains what [`icr2multicar.py`](icr2multicar.py) changes in
**native Windows IndyCar Racing II v1.0.1 (`WINDY.EXE`)** and how the
injected x86 routine works. It is written for modders and reverse engineers.
For downloads and ordinary usage, see the [README](README.md).

**Scope and status:** The application runs as a live memory modifier: it
does **not** patch `WINDY.EXE` on disk or rewrite carset/3DO files. Its
chassis and wheel/tire hooks have been exercised in live WINDY sessions,
including shutdown after the game exits. That does not establish that every
combination of chassis, wheel shapes, cameras, replay or race states is
fully validated. In particular, this hook reuses the game's wheel-rotation
code; it is **not** an independent wheel-animation engine.

## 1. Why both hooks are needed

Stock WINDY keeps pointers to the geometry associated with individual cars,
but an existing assignment can replace a selected car's geometry pointer
with a shared/default model. The game also maintains four global wheel-node
slots and four global wheel-appearance destinations used by the ordinary
tire-selection and wheel-rotation code.

Multi-Car makes two coordinated changes:

1. **Preserve the selected car's chassis geometry.** NOP a two-byte
   store that overwrites the per-car geometry pointer.
2. **Use the current car's four wheel nodes.** Intercept the call to
   the game's tire-selection routine. Immediately before continuing,
   locate the geometry pointer for the car being drawn, resolve its first
   four wheel child slots, and redirect the game's existing wheel-node
   and appearance-destination tables to those nodes. Then run the
   original tire selector and continue the original wheel transforms.

The result is support for differing body and wheel/tire geometry
using the carset's existing references. Multi-Car does **not** choose
chassis by driver name, preload arbitrary additional models, create
3DO resources, or change the physics engine.

## 2. Version, addresses and on-disk versus live changes

| Property | Value |
| --- | --- |
| Target | Native Windows IndyCar Racing II `WINDY101` (v1.0.1) |
| Executable | `WINDY.EXE`, 32-bit x86 Portable Executable (PE) |
| Required PE image base | `0x00400000` |
| Runtime memory API | ICR2Runtime **v0.13**, code writes explicitly enabled |
| Code cave | **80-byte** x86 routine inside a new **4096-byte** remote allocation |
| Operation | Temporary writes into the *running* WINDY process |
| Exit | Restore both instruction sites when possible; otherwise Windows discards the terminated process's address space |

The code reports **Ghidra virtual addresses (VAs)**. For this native
build, ICR2Runtime's translation base must be **zero** and the host PE
module base must equal `0x00400000`. These VAs are therefore the
corresponding in-process addresses; they are **not** raw file offsets.

For independent inspection of the examined original PE, the code
section begins at **file offset `0x600`** and maps to VA
**`0x00410000`**. Within that code section only:

```text
file_offset = virtual_address - 0x00410000 + 0x600
```

For example, VA `0x0045B719` corresponds to raw `0x4BD19`,
and VA `0x004607C0` to raw `0x50DC0`. The data tables listed below
are runtime addresses and should **not** be converted with this
code-section formula.

A reference `WINDY.EXE` used for byte verification was **1,916,928
bytes**, SHA-256
`eb467955aba9160ac7bd1c0465482b1146139f40abb9ea5a795841c7bc0665bf`.
**This hash is informational, not a whole-file hash requirement
implemented by the patcher.** In operation, the runtime identifies
`WINDY101` and the tool verifies the address layout and precise
instruction signatures described below. An executable with a
different hash is **not automatically compatible**.

## 3. Complete instruction patch map

Only **two existing instruction locations** are overwritten in the
running game. A separate executable allocation holds the new routine.

| WINDY virtual address | Raw offset in examined PE | Original instruction bytes | Memory patch | Purpose |
| --- | --- | --- | --- | --- |
| `0x0045B719` | `0x4BD19` | `89 02` | `90 90` | Suppress store of shared geometry pointer |
| `0x004607C0` | `0x50DC0` | `E8 34 ED FF FF` | `E9 xx xx xx xx` | Replace tire-selector `CALL` with a near `JMP` into injected routine |
| **Allocated at runtime** | **No file offset** | No original bytes (new memory) | 80-byte position-fixed x86 payload, relocated at installation | Update wheel-node/appearance pointers, call original selector, rejoin renderer |

The wheel hook's `E9` displacement is generated **for each run**:
the destination is the address returned by `VirtualAllocEx`, so there
is no universal five-byte replacement sequence. It is encoded as:

```text
E9 + signed 32-bit little-endian (cave_address - (0x004607C0 + 5))
```

**The original five-byte call:**

```asm
; WINDY at 0x004607C0, bytes E8 34 ED FF FF
call 0x0045F4F9      ; existing front/rear tire-appearance selector

; Patched at exactly the same VA:
jmp code_cave        ; dynamic rel32 destination
```

After completing its work, the cave itself calls
`0x0045F4F9` and jumps back to **`0x004607C5`**, immediately
after the overwritten original `CALL`. The original stack cleanup
(`add esp, 8`) and subsequent wheel-update instructions are retained.

## 4. Chassis geometry preservation

At **VA `0x0045B719`**, two bytes change:

```asm
; Before: 89 02
mov dword ptr [edx], eax

; After: 90 90
nop
nop
```

The surrounding verified stock instructions are:

```asm
mov dword ptr [edx*4+0x00513660], eax
mov eax, dword ptr [0x005147A0]
mov eax, dword ptr [eax]
mov edx, dword ptr [edx*4+0x00513660]
mov dword ptr [edx], eax          ; the disabled instruction
```

This stores a shared/default model pointer through the pointer slot
for the selected car. NOPing the final store allows the individual
geometry pointer to remain in place. The previous computation and
assignment of the slot pointer at `0x00513660` are **not**
modified by this patch.

ICR2Runtime uses a guarded `PATCH_CODE` operation. The tool requires
the exact original `89 02`, records the original bytes for restoration,
and refuses an unknown or untracked patch state.

## 5. Injected wheel/tire pointer redirector

### 5.1 Which stock code it intercepts

Immediately before the original call at `0x004607C0`, WINDY obtains
the current car index from the render context (`[esi]` → `+0x74`)
and pushes two arguments for the original tire selector. Immediately
after the call it runs the game's existing wheel-rotation calls,
including one at **`0x004A6FEE`** that writes the Z, Y and X
rotation fields for a wheel node.

The injected code runs *between* argument setup and that original
call. It preserves flags and general registers around its pointer
redirection, and then restores them before executing the original
selector.

### 5.2 Annotated disassembly of the 80-byte code cave

The code lives at a **dynamically allocated VA**, not a fixed game VA.
Offsets below are relative to the start of that allocation. Symbolic
names represent operands filled in by `build_cave()`:

```asm
+00  pushfd
+01  pushad
+02  mov eax, [esi]
+04  mov eax, [eax+0x74]             ; current car index
+07  cmp eax, 0x20                  ; 0..32 (33 cars)
+0A  ja  done
+0C  mov edi, [eax*4 + 0x00513660] ; chassis pointer slot for car
+13  test edi, edi
+15  jz  done
+17  xor ebx, ebx                   ; wheel child index 0..3

loop:
+19  push ebx
+1A  push edi
+1B  call 0x004A6FB0                ; resolve child's pointer slot
+20  add esp, 8
+23  test eax, eax
+25  jz  done                       ; unsupported child layout
+27  mov [ebx*4 + 0x00514760], eax ; wheel-node pointer slot
+2E  mov edx, [eax]                 ; actual wheel node pointer
+30  test edx, edx
+32  jz  done
+34  lea edx, [edx+0x1C]           ; wheel appearance field address
+37  mov [ebx*4 + 0x00514780], edx ; destination used by tire selector
+3E  inc ebx
+3F  cmp ebx, 4
+42  jl  loop

done:
+44  popad
+45  popfd
+46  call 0x0045F4F9                ; execute original tire selector
+4B  jmp 0x004607C5                 ; return after intercepted call
```

The listing shows **all 80 bytes**, from offset `+0x00` through
`+0x4F`. The four-wheel loop updates **global pointer tables
used by stock game code**; it does not itself calculate wheel angle,
select tire textures, or directly write the animation fields.

### 5.3 What the helper at 0x004A6FB0 returns

The injected routine calls an **existing WINDY function**
at `0x004A6FB0` with:

- `[esp+4]`: pointer to the car-specific chassis slot (`EDI`);
- `[esp+8]`: child index (`EBX`, 0–3).

The stock helper dereferences the chassis root, checks its first
32-bit field for type **`0x10`** (F16-style `SUPEROBJ`), and
returns the address of a child-pointer slot at
`root + 0x0C + index*4`. Otherwise it returns zero.

The cave checks the returned slot and dereferences it to obtain the
actual wheel child pointer. This is the **only explicit model-type
check** in this path: the cave does *not* independently validate the
type of each child. Thus the patch assumes compatible wheel children
0–3 and cannot be considered safe for arbitrary 3DO hierarchies.

### 5.4 Global pointer tables changed at runtime

These addresses are **WINDY in-memory data structures**, not
additional static executable-instruction patch sites:

| VA | Values read/written by the injected routine | Effect |
| --- | --- | --- |
| `0x00513660` | **Read:** up to 33 pointers to per-car chassis slots | Finds the current car's geometry slot |
| `0x00514760` | **Write:** four consecutive 32-bit pointers | Point the original animation calls at the selected chassis's wheel child slots |
| `0x00514780` | **Write:** four consecutive 32-bit pointers | Point the original tire selector at each wheel child's `+0x1C` appearance field |

For `i = 0..3` the cave computes:

```text
chassis_slot = *(0x00513660 + car_index*4)
wheel_slot   = resolve_child_slot(chassis_slot, i)
wheel_node   = *wheel_slot

*(0x00514760 + i*4) = wheel_slot
*(0x00514780 + i*4) = wheel_node + 0x1C
```

The original tire selector at `0x0045F4F9` obtains appropriate
front/rear appearance references and writes through the four
addresses stored at `0x00514780`. Its first two destinations
receive the front appearance; the other two receive the rear
appearance.

The original wheel-animation code that follows `0x004607C5`
continues to call `0x004A6FEE`, passing the pointers
from `0x00514760` and its existing spin/steering arguments.
That stock function writes rotational fields at offsets
**`+0x10`, `+0x14`, `+0x18`** in each targeted wheel node.

**Important limitation:** This is pointer redirection into
WINDY's *existing* wheel/tire logic. It is not an independent
replacement for wheel rotation or an additional per-car animation
clock. The global tables are rewritten for the current render
context; the script does **not** separately snapshot and restore
those data-table values at shutdown. It restores the two
patched *instruction sites*.

### 5.5 Dynamic code relocations

The Python `build_cave(base, image_base)` function writes the 80-byte
template then fills these four-byte fields. Absolute pointers use
little-endian VA values; `rel32` values are relative to the byte
following the displacement:

| Cave displacement offset | Type | Destination |
| --- | --- | --- |
| `+0x0F` | 32-bit absolute | `0x00513660` — per-car chassis slots |
| `+0x1C` | 32-bit relative `CALL` | `0x004A6FB0` — wheel child-slot resolver |
| `+0x2A` | 32-bit absolute | `0x00514760` — wheel node slots |
| `+0x3A` | 32-bit absolute | `0x00514780` — appearance destinations |
| `+0x47` | 32-bit relative `CALL` | `0x0045F4F9` — original tire selector |
| `+0x4C` | 32-bit relative `JMP` | `0x004607C5` — return to renderer |

The code contains a small number of constant internal short branches;
their displacements are already embedded in the 80-byte template.
Because the cave address is assigned by Windows, every `rel32` must
be recomputed at installation time.

## 6. Installation sequence and safety checks

The public Multi-Car script works with **ICR2Runtime v0.13** and the
Win32 process/memory APIs:

1. Query the shared runtime and select exactly one process identified
   as `WINDY101`. Refuse unknown versions or ambiguous multiple PIDs
   unless `--pid` is provided.
2. Require the native PE base `0x00400000` and translation base zero;
   verify the wheel call's original five bytes and the chassis
   store's original two bytes.
3. Check that neither site already has conflicting or untracked
   patch state. Require the runtime capability `PATCH_CODE`.
4. Open a handle to the WINDY process with process-memory and
   synchronization rights.
5. Allocate **4096 bytes** inside WINDY using `VirtualAllocEx`,
   initially `PAGE_READWRITE`. Assemble the **80-byte** code cave,
   write it with `WriteProcessMemory` and verify a byte-for-byte
   readback through ICR2Runtime.
6. Use `VirtualProtectEx` to change the page protection to
   `PAGE_EXECUTE_READ`, then call `FlushInstructionCache`.
7. Apply the **five-byte wheel JMP first** with a guarded runtime
   `PATCH_CODE`; reread and verify it. Then apply the **two-byte
   chassis NOP** using another guarded `PATCH_CODE` operation and
   verify the runtime-tracked record.
8. While active, check the instruction bytes and chassis patch
   record roughly once a second; detect a terminated WINDY process
   through the *original process handle*.

**Why the separate runtime?** ICR2Runtime verifies exact expected
bytes and owns the two instruction patch/restore records. The Python
tool separately allocates the executable cave and manages its
lifetime using Win32 APIs. A successful patch operation does
not mean that a future restoration is guaranteed after arbitrary
crashes or interference from other modding tools.

`check` is read-only (and requires an already-running ICR2Runtime
service). `run` starts the service when needed with
`--enable-code-writes`. An existing read-only runtime instance is
not silently upgraded.

## 7. Shutdown, restoration and limits

**Preferred:** Press **Ctrl+C** while WINDY is still running.

The tool verifies that the wheel JMP and its runtime patch record
are the expected ones; restores the **original
`E8 34 ED FF FF`** at `0x004607C0`; restores the chassis
**`89 02`** at `0x0045B719`; then pauses approximately
0.5 seconds before freeing the executable cave.

If a wheel JMP could still target the cave, the tool **does not
free it**: doing so would leave a live jump into released memory.
The half-second delay reduces, but does not mathematically
eliminate, the possibility that a render thread is still
executing the cave. Restoration is best-effort and requires
the game and runtime to remain accessible.

**If WINDY exits first:** `WaitForSingleObject` signals that
the original process has terminated. Windows then reclaims
the entire process address space, including both modified
instruction pages and the injected cave; there is no live
memory to restore, so the script exits normally. It does
not mistake a reused PID for the original process.

**Compatibility bounds:** The cave accepts indices 0–32,
expects a compatible type-`0x10` chassis hierarchy with
four accessible children, and relies on the stock tire and
wheel-transform functions remaining at their verified VAs.
There are no game EXE disk changes or driver-to-chassis
mapping changes. Competing injectors, unusual 3DO structures,
replays/camera paths, reloads and abrupt process termination
remain relevant tests.

The patch contains no new texture loader, no altered tire
selection algorithm, and no independent wheel-animation
engine. Community testing should distinguish visual
chassis/wheel/tire correctness from successful installation
and restoration of instruction patches.

Do not distribute modified proprietary game binaries
with this tool. Distribute the patcher and use your own
licensed copy of the original game.
