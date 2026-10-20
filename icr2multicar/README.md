# ICR2 Multi-Car Models

Enable different car chassis models, wheel geometry, and tire appearances
for individual cars in the native Windows version of *IndyCar Racing II*
(WINDY101).

The tool uses **one Python script**: `icr2multicar.py`. Running it enables
both chassis and wheel/tire hooks together. It changes memory in the
running game only; it does not modify `WINDY.EXE` or carset files on disk.

## Requirements

- Windows with a supported native **WINDY101** game process (*IndyCar Racing II*
  Windows v1.0.1).
- Python **3.9+**.
- **ICR2Runtime v0.13** and its matching `icr2_client.py` and
  `runtime_launcher.py`. See the [runtime build guide](../icr2runtime/README.md#build-on-windows).
- A compiled `icr2runtime.exe`, started with `--enable-code-writes` for
  patching.

Keep `icr2multicar` and `icr2runtime` beside each other:

```text
icr2tools/
  icr2runtime/
    icr2_client.py
    runtime_launcher.py
    build/Debug/icr2runtime.exe
  icr2multicar/
    icr2multicar.py
```

The script and runtime client require no third-party Python packages.

## Usage

1. Start WINDY101 and select the carset you want to use.
2. Start ICR2Runtime with code writes enabled. From the repository root:

   ```powershell
   .\icr2runtime\build\Debug\icr2runtime.exe --enable-code-writes
   ```

   Stop an already-running read-only service before starting a
   code-write-enabled one. Existing service permissions cannot be
   upgraded automatically.

3. Inspect the game without changing memory:

   ```powershell
   python icr2multicar\icr2multicar.py check
   ```

   Both the chassis and wheel/tire sites must report `READY`.

4. Enable both hooks:

   ```powershell
   python icr2multicar\icr2multicar.py run
   ```

   Keep the terminal open while playing. **Ctrl+C** attempts to restore
   both instructions and free the allocated code page. Do not close WINDY
   or the runtime while the tool is running.

If multiple supported WINDY processes are running, specify
`--pid <process-id>`. You may provide
`--runtime-exe <path-to-icr2runtime.exe>` to `run` when the
tool needs to start the runtime automatically. A `check` action
requires an already-running runtime.

## How it works

The tool applies two changes together:

1. **Chassis geometry:** Changes the instruction at `0x0045B719`
   from `89 02` to `90 90`, preventing the game from forcing one
   shared chassis geometry pointer.
2. **Wheels and tires:** Redirects the original call at `0x004607C0`
   to a small x86 routine allocated in WINDY. That routine selects
   wheel geometry and tire appearances for the active car before
   returning to the game's code.

Both edits to the game's existing instructions use ICR2Runtime's
guarded `PATCHCODE` and `RESTORE` operations. The Python script
allocates and manages the extra code page using Windows process-memory
APIs. The tool does **not** provide separate per-car wheel animation.

## Safety and compatibility

- The tool only supports the WINDY101 build and the validated instruction
  layout. It checks the target process, original bytes, and runtime patch
  tracking before modifying memory.
- **The combined wheel/tire hook has not yet been validated in a live
  WINDY session.** Its instruction layout and relocations were checked
  offline, but actual in-game behavior still requires testing.
- Do not run other memory injectors that modify these sites or run
  multiple copies of this script against the same game process.
- Restoring instructions is not atomic with game execution. Abrupt
  termination, conflicting patches, or stopping during rendering can
  prevent cleanup or crash WINDY.
- If the wheel jump cannot be safely detached, the script leaves the
  extra code page allocated rather than free memory still being used
  by the game. Close WINDY after an unsuccessful restoration.
- No game executable, carset, or copyrighted game assets are included.

These tools are independent community modifications and are not
affiliated with the game's original developers or publishers.
