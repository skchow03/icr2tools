# ICR2 Multi-Car Models

Windows-only tools for enabling individual car chassis models and wheel/tire
appearances in the native Windows version of *IndyCar Racing II* (WINDY101).
The tools modify game memory while WINDY is running; they do not change
`WINDY.EXE` or your carset files on disk.

## Tools

| Script | Function | Commands |
| --- | --- | --- |
| `windy_multichassis.py` | Allows each car to retain its selected chassis geometry instead of using one shared model pointer. | `check`, `on`, `off`, `run` |
| `windy_wheel_tire.py` | Enables the chassis change and updates wheel geometry and tire appearance pointers for each car. | `check`, `run` |

Both scripts verify the detected game and original instruction bytes before
writing. `check` is read-only. `run` keeps the patch active until
**Ctrl+C**, then attempts to restore the original instructions. The
chassis-only script also offers `on` and `off` to manage its separately
tracked two-byte patch.

These tools do **not** provide separate per-car wheel animation.

## Requirements

- **Windows**, with a supported native **WINDY101** (*IndyCar Racing II*
  Windows v1.0.1) game process.
- **Python 3.9+**.
- **ICR2Runtime v0.13**, including the matching `icr2_client.py` and
  `runtime_launcher.py` from the [runtime directory](../icr2runtime/).
- A compiled `icr2runtime.exe` with code writes explicitly enabled.

See [ICR2Runtime's build instructions](../icr2runtime/README.md#build-on-windows)
to compile the service with CMake and MSVC. No third-party Python packages
are needed for these wrappers.

Keep the repository directories together so the scripts can import the
runtime client:

```text
icr2tools/
  icr2runtime/
    icr2_client.py
    runtime_launcher.py
    build/Debug/icr2runtime.exe
  icr2multicar/
    windy_multichassis.py
    windy_wheel_tire.py
```

## Quick start

1. Start WINDY101 and load the carset you want to use.
2. Start **ICR2Runtime v0.13** with permission to patch code. For example,
   from the repository root:

   ```powershell
   .\icr2runtime\build\Debug\icr2runtime.exe --enable-code-writes
   ```

   An already-running read-only service cannot be upgraded automatically.
   Stop it before starting a code-write-enabled instance.
3. Check the original instructions without modifying the game:

   ```powershell
   python icr2multicar\windy_wheel_tire.py check
   ```

   Both the chassis and wheel/tire sites must report `READY`.
4. Start the combined multi-car hook:

   ```powershell
   python icr2multicar\windy_wheel_tire.py run
   ```

   Keep this terminal open while playing. Press **Ctrl+C** to attempt a
   clean restoration before exiting WINDY.

To enable **chassis geometry only**, use:

```powershell
python icr2multicar\windy_multichassis.py check
python icr2multicar\windy_multichassis.py run
```

The chassis-only script also supports `on` (apply and exit) followed by
`off` (restore), provided the same runtime service still tracks the patch.
Do not run both wrappers simultaneously. If several WINDY processes are
detected, pass `--pid <process-id>`. You can pass
`--runtime-exe <path-to-icr2runtime.exe>` when the script needs to start
the service itself; an existing service must already have the required
write capability.

## How it works

The chassis wrapper replaces the verified WINDY101 instruction at
`0x0045B719` (`89 02`) with two NOPs (`90 90`), preventing the game
from forcing a shared chassis geometry pointer.

The combined wrapper also redirects the call at `0x004607C0` into a
small x86 routine allocated inside WINDY. This routine selects the wheel
and tire appearance pointers for the current car and resumes the game's
original code. Both original instruction patches use ICR2Runtime's
guarded `PATCHCODE` and `RESTORE` operations. The combined wrapper
manages its own allocated code page with Windows process-memory APIs.

## Safety and compatibility

- **Use a disposable game session and back up any important files.** These
  are memory hooks for a specific game build, not general-purpose patches.
- The combined wheel/tire hook has **not yet been verified in a live
  WINDY session**. Its instruction layout and relocation calculations have
  been checked, but actual in-game behavior still requires validation.
- Do not enable another injector or script that changes the same code sites.
  Unexpected bytes, address layouts, or runtime patch records are rejected.
- The combined hook must remain under the control of its `run` process.
  If restoration cannot be confirmed, it deliberately leaves the allocated
  code page in place to avoid a dangling jump.
- Restoration is not atomic with game execution. Abrupt termination, other
  memory patches, or stopping during rendering can prevent cleanup or crash
  WINDY. If cleanup fails, close WINDY before trying again.
- The tools do not include or distribute any game executable, carset, or
  copyrighted game assets.

These utilities are independent community modifications and are not
affiliated with the original game's developers or publishers.
