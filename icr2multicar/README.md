# WINDY Multi-Chassis + Per-Car Wheels/Tires (experimental v0.2)

This folder contains two **Windows-only** Python wrappers for the native
WINDY101 build of *IndyCar Racing II*. It uses **ICR2Runtime v0.12** for game
detection and guarded executable-code patches. No ICR2Runtime C++ change is
required for this experiment.

## Original working chassis-only wrapper

`windy_multichassis.py` is carried forward unchanged from v0.1. It patches
`0x0045B719: 89 02 -> 90 90`, preventing WINDY from overwriting the car's
selected geometry pointer. Its `check`, `on`, `off`, and `run` commands retain
the original behavior, and the first-stage change has already been verified in
WINDY.

## New combined wheel/tire wrapper

`windy_wheel_tire.py` reproduces the **third** Cheat Engine table entry,
**Per-Car Wheels and Tires**, in the supplied `WINDY_carmodel.CT`:

- Hooks `WINDY.EXE+0x607C0` (`0x004607C0`, original bytes `E8 34 ED FF FF`).
- Allocates an 80-byte x86 routine inside WINDY, in a private 4096-byte page.
- Resolves the current car index from `[esi]`, then `[eax+0x74]` (indices 0–32).
- Finds the car's model pointer in `[eax*4+0x00513660]`.
- Calls the original wheel-finding routine at `0x004A6FB0` for four wheels.
- Updates wheel pointers at `0x00514760` and tire appearance pointers at
  `0x00514780`.
- Calls WINDY's displaced original tire-selection function at `0x0045F4F9`.
- Returns to `0x004607C5` (just beyond the replaced five-byte CALL).
- Also enables the verified two-byte chassis NOP patch.

The separate Cheat Engine entries **Mixed AI Car Models** and **Per car wheel
animation** are NOT installed. **Do not enable those scripts simultaneously
with this wrapper**, since they target overlapping/related instructions.

### Important implementation detail

The v0.12 runtime can patch existing instructions but **cannot allocate new
executable pages** in a game process. The new Python wrapper uses Windows
`VirtualAllocEx`, `WriteProcessMemory`, `VirtualProtectEx`, and
`FlushInstructionCache` to allocate and populate its code cave. Both changes
to WINDY's **original code instructions** go through the runtime's guarded
`PATCHCODE`/`RESTORE` API and patch tracker. Code cave cleanup is owned by this
wrapper, not by ICR2Runtime. If the wrapper crashes, patch tracking and remote
allocation cleanup are not guaranteed; close WINDY to discard its process
memory in that case. This is a test implementation, not a hardened injection
subsystem.

### Install

Place the two Python scripts in a sibling folder next to `icr2runtime`:

```text
ICR2Tools/
  icr2runtime/
    icr2_client.py
    runtime_launcher.py
    build/Debug/icr2runtime.exe
  icr2multicar/
    windy_multichassis.py
    windy_wheel_tire.py
```

Use the current **v0.12** runtime and Python client, not an older v0.11 binary.

### Test in stages

1. **Stop the old chassis-only wrapper with Ctrl+C.** Do not run the wheel-only
   or combined Cheat Engine scripts. Start WINDY101 and leave it running.
2. Start v0.12 ICR2Runtime **with code writes enabled** (not required for check):

   ```powershell
   cd icr2runtime
   .\build\Debug\icr2runtime.exe --enable-code-writes
   ```

   If the shared v0.12 runtime is already running read-only, close it first;
   the launcher will not silently upgrade its permissions.
3. From the ICR2Tools repository root, perform a read-only check:

   ```powershell
   python icr2multicar\windy_wheel_tire.py check
   ```

   Confirm the chassis site is `89 02 / READY` and wheel/tire site is
   `E8 34 ED FF FF / READY`.
4. **Only when both checks pass**, run the combined patch:

   ```powershell
   python icr2multicar\windy_wheel_tire.py run
   ```

5. Test a multi-model carset. Leave this terminal open. **Ctrl+C** attempts to
   restore the wheel detour and the chassis instruction; it then releases the
   injected code page after a short delay.

### Safeguards and limits

- Read-only `check` cannot allocate or patch memory.
- `run` verifies WINDY version, its default PE image base, and both exact
  original instruction sequences. Unknown bytes and existing runtime-tracked
  patches are rejected rather than adopted.
- A 32-bit process-only code cave is allocated with RW permissions, verified,
  and changed to RX (not writable/executable at the same time).
- `run` maintains the session; there is **no persistent `on` command** for the
  combined hook, because the code cave lifetime needs a manager.
- Code restoration is not atomic with game execution. Stopping during active
  rendering, conflicting injectors, external process termination, or abrupt
  interpreter shutdown can still crash WINDY or prevent cleanup. Use a test
  carset and quit the game after unsuccessful restoration.
- If the wheel JMP cannot be verified as detached, the wrapper intentionally
  **does not free** its code cave while the detour might still reference it.
- The code was assembled/disassembled and its address relocations checked
  offline. **The combined wheel/tire hook has not yet been tested in live WINDY.**
- The supplied game EXE and Cheat Engine script are used for validation only;
  they are not included in this package.
