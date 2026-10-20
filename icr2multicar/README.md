# ICR2 Multi-Car Models

ICR2 Multi-Car allows cars to use their own chassis shapes, wheel geometry,
and tire appearances in the **native Windows version of IndyCar Racing II
(WINDY101)**. One Python script enables both changes together.

The tool modifies the running game's memory. It does **not** change game
files or carsets on disk.

## What you need

- The native Windows version of *IndyCar Racing II* (WINDY101, v1.0.1).
- Windows and Python 3.9 or newer.
- The **[ICR2Runtime v0.13 Windows download](https://github.com/skchow03/icr2tools/releases/download/icr2runtime-v0.13/ICR2Runtime-v0.13-win64.zip)**.

**No C++ compiler, CMake, or runtime build is required.**

## Set up

1. Download the [`icr2multicar.py` script](icr2multicar.py) from this folder
   (on GitHub, open the file and choose **Download raw file**).
2. Download and extract the ICR2Runtime ZIP linked above.
3. From the extracted ZIP's `ICR2Runtime` folder, copy
   `icr2runtime.exe`, `icr2_client.py`, and `runtime_launcher.py`
   into the **same folder** as `icr2multicar.py`.

Your folder should look like this:

```text
ICR2MultiCar/
  icr2multicar.py
  icr2runtime.exe
  icr2_client.py
  runtime_launcher.py
```

## Play

1. Start WINDY101.
2. Open a terminal in the folder shown above.
3. Run:

   ```powershell
   python icr2multicar.py run
   ```

Multi-Car automatically starts the included ICR2Runtime executable with
the permission needed to enable both hooks. **You do not need to run
`icr2runtime.exe` separately.**

Keep the terminal open while playing. When you're finished, press
**Ctrl+C** in the terminal and allow the script to restore the game
instructions before closing WINDY.

## Troubleshooting

- **No WINDY101 game detected:** Make sure the *native Windows* game is
  running; the tool does not support the DOS or Rendition versions.
- **A runtime is already running without code-write permission:** Close
  the existing `icr2runtime.exe` process, then run the Multi-Car command
  again. The tool will launch the released EXE with the needed permission.
- **Python is not recognized:** Install Python 3.9+ and make sure it is
  available on your command line. On some Windows systems, `py` works
  instead of `python`.

For troubleshooting, `python icr2multicar.py check` can inspect the
game's hook sites **without changing memory**, but it requires an
already-running ICR2Runtime service. Normal use only requires `run`.

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
