# REND32A multi-chassis: live-signature Stage 2

Experimental two-byte chassis patch using ICR2Runtime v0.12. **No C++ runtime changes.** No wheel/tire hook. This replaces the previous `rend32a_multichassis.py`, whose hard-coded offset was incorrect for the loaded REND32A code.

The read-only locator found one matching function prelude at `0x049967`, a tail at `0x04998D`, and the `89 02` instruction at `0x04998F` in one running REND32A session. **These are observations, not hard-coded addresses:** this script searches again for each new process.

The script verifies the prelude, the 0x26-byte spacing, and the tail while allowing either the original `89 02` or patched `90 90` in the two-byte slot. The code patch itself is applied using ICR2Runtime's guarded `PATCHCODE` and restored via its tracked `RESTORE` command.

## Installation

Copy `rend32a_multichassis.py` into your existing `icr2multicar/` folder, replacing the old file. It imports the current `icr2_client.py` and `runtime_launcher.py` from the sibling `icr2runtime/` folder.

## Commands from ICR2Tools root

With REND32A running, and ICR2Runtime v0.12 running with `--enable-code-writes` (or auto-startable from the wrapper):

```powershell
python icr2multicar\rend32a_multichassis.py check
python icr2multicar\rend32a_multichassis.py run
```

`check` is read-only. `run` installs the temporary NOP, keeps checking the patch, and **attempts restoration on Ctrl+C**. You can also use `on` and `off` to apply/restore independently. Multiple games require `--pid <DOSBOX_PID>`.

## Safety and limitations

- **Use a disposable session**; do not enable a Cheat Engine script for the same instruction.
- A matching function signature does not prove that NOPing the instruction will enable multiple chassis or that DOSBox's dynamic core will recognize the change.
- Never manually modify memory if the wrapper reports an unexpected or untracked patch.
- Ctrl+C restoration is best-effort, not crash-proof. If restoration fails, read the error and verify original bytes before continuing.
- Do not reload or close REND32A/DOSBox while patched. No Rendition-specific wheel/tire modification is included.
