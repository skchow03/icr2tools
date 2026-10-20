# ICR2 Multi-Car Models

ICR2 Multi-Car allows cars to use their own chassis shapes, wheel geometry,
and tire appearances in the **native Windows version of IndyCar Racing II
(WINDY101)**. One Python script enables both changes together.

The tool modifies the running game's memory. It does **not** change game
files or carsets on disk.

## Download the Windows application

For the simplest setup, download **ICR2MultiCar Windows** from the
[ICR2Tools releases](https://github.com/skchow03/icr2tools/releases)
once a Multi-Car release is published. Extract its ZIP, start WINDY101,
then run `ICR2MultiCar.exe run` from a terminal in the extracted folder.

The packaged EXE contains both the Python application and its matching
ICR2Runtime service. **No Python installation, runtime download, or
compilation is needed.** Keep the console open while playing and press
**Ctrl+C** to attempt to restore both hooks before closing WINDY.

### Using the Python script instead

If you prefer the source version, you need Python 3.9+ and
[ICR2Runtime v0.13 for Windows](https://github.com/skchow03/icr2tools/releases/download/icr2runtime-v0.13/ICR2Runtime-v0.13-win64.zip).

Place `icr2multicar.py` beside the extracted `icr2runtime.exe`,
`icr2_client.py`, and `runtime_launcher.py`, then run:

```powershell
python icr2multicar.py run
```

Both distributions automatically start the runtime with the necessary
permissions. There is no need to start `icr2runtime.exe` yourself.

## Troubleshooting

- **No WINDY101 game detected:** Make sure the *native Windows* game is
  running; the tool does not support the DOS or Rendition versions.
- **A runtime is already running without code-write permission:** Close
  the existing `icr2runtime.exe` process, then run the Multi-Car command
  again. The tool will launch the released EXE with the needed permission.
- **Python is not recognized:** Use the packaged Windows EXE instead, or
  install Python 3.9+ to run the source script.

For troubleshooting, `ICR2MultiCar.exe check` (or
`python icr2multicar.py check` for the source version) inspects the hook
sites **without changing memory**, but requires an already-running
ICR2Runtime service. Normal use only requires `run`.

## Compatibility and safety

- Only the supported **WINDY101** executable layout is recognized.
- **The combined wheel/tire hook has not yet been confirmed in a live
  WINDY session.** Treat this as an experimental modification.
- Do not use multiple copies of Multi-Car or other tools that patch the
  same game instructions at the same time.
- Memory modifications can crash the game. Forced termination or
  conflicting patches can prevent clean restoration. If the script
  reports that cleanup failed, close WINDY before trying again.
- This does not add independent wheel animation to each car.

No game executables or copyrighted game assets are included. This is an
independent community modification, unaffiliated with the game's original
developers or publishers.
