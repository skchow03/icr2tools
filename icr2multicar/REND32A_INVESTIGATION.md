# REND32A multi-chassis investigation — stage 1

**Status:** Static executable analysis complete for a candidate chassis overwrite; **not yet tested live**. No Rendition code cave or wheel/tire hook is included.

## Why this candidate is unusually strong

The uploaded `CART.EXE` is a DOS/32A **LE (Linear Executable)**, not a Windows PE. Its LE object table shows executable object 1 starting at guest virtual address `0x00010000` and raw code pages at file offset `0x0004BE20`. Thus, within this object's mapped code pages:

```text
Ghidra/guest address = 0x10000 + (raw_file_offset - 0x4BE20)
```

The following raw bytes from the uploaded file disassemble at guest address `0x00044C87`:

```asm
44C87  add eax,1Ch
44C8A  mov eax,[eax]
44C8C  add eax,0Ch
...    ; navigate geometry-pointer structure
44C9C  mov [edx+0003C1C8h],eax ; save pointer for selected car
44CA2  mov eax,[0003E434h]   ; fetch shared default model source
44CA7  mov edx,[edx+0003C1C8h]
44CAD  mov eax,[eax]
44CAF  mov [edx],eax           ; CANDIDATE FOR NOP NOP
44CB1  add esp,4
44CB4  pop esi
44CB5  pop edx
44CB6  pop ecx
44CB7  pop ebx
44CB8  ret
```

Exact `44C9C` comment is explanatory; the machine instruction is `mov [edx+0x3C1C8],eax` (indexing an individual car geometry slot).

Compare the verified WINDY101 routine:

```asm
45B704  mov [edx*4+00513660h],eax ; save per-car model pointer
45B70B  mov eax,[005147A0h]      ; shared model source
45B710  mov eax,[eax]
45B712  mov edx,[edx*4+00513660h]
45B719  mov [edx],eax            ; the verified WINDY NOP site
```

The same geometry structure traversal, model selection and final shared-model overwrite are visible in both builds, despite compiler/register differences. The REND32A candidate's original two bytes are **`89 02`**, at **Ghidra address `0x44CAF`** or **raw CART.EXE offset `0x80ACF`**.

**Important:** Additional writes to car model slots occur in the Rendition drawing functions around `0x2AE4B`, `0x2AECE`, and `0x2AFD5`. They have not been modified or proven equivalent to a required wheel/tire hook. Stage 1 only tests whether removing the one shared-model override is sufficient to expose distinct chassis. It may not be, and tires/wheels may still misbehave.

## Working folder

Extract `rend32a_multichassis.py` into the existing `icr2multicar` folder, adjacent to the WINDY wrappers. It imports `icr2_client.py` and `runtime_launcher.py` from a sibling `icr2runtime` directory.

## Instructions — read-only first

With REND32A running in DOSBox and ICR2Runtime **v0.12** running (default read-only), from the `ICR2Tools` root:

```powershell
python icr2multicar\rend32a_multichassis.py check
```

Expected if the live code matches the uploaded binary:

```text
REND32A PID ...; candidate 0x00044CAF; bytes: 89 02; state: READY
Rendition function-context check: MATCH (read-only)
```

This test verifies the live guest code bytes, NOT the visual effect of a patch. **Stop here and share the read-only output before enabling writes.**

## Only if read-only verification passes

Stop a running read-only runtime, then restart it from `icr2runtime` with code writes enabled:

```powershell
.\build\Debug\icr2runtime.exe --enable-code-writes
```

From the `ICR2Tools` root:

```powershell
python icr2multicar\rend32a_multichassis.py run
```

The wrapper modifies only two bytes, uses the runtime's expected-byte check, verifies tracking, and attempts restoration on Ctrl+C. Use a disposable game session; do not run a Cheat Engine patch simultaneously. A DOSBox dynamic CPU core might cache previously translated code, so memory readback alone is not proof that the change took effect. Avoid reloading the game or switching tracks while patched.

A failed restoration must be treated as **unresolved**, not automatically safe; the terminal reports it. Never manually modify guest memory without verifying the current state and original bytes.

## What comes next

If geometry unlock works, identify the Rendition-specific wheel animation and tire appearance pointer-selection code by disassembling the engine's rendering functions. If geometry does not unlock, inspect the other car model overwrites and whether DOSBox has retranslated the patched guest instruction before changing anything else.
