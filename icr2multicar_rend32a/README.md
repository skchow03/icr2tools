# ICR2 Multi-Car — Rendition (REND32A)

Create a modified **Rendition version** of *IndyCar Racing II* with multiple
car chassis and per-car wheel/tire support.

**Experimental:** The underlying FOUR V2 + C2 wheel patch was tested in-game,
but the configurable chassis-name preloader still needs live DOSBox testing.
This is separate from the [Windows WINDY Multi-Car tool](../icr2multicar/).

## Requirements

- Python 3.10 or newer.
- Your own **original, unmodified REND32A `CART.EXE`** (1,109,095 bytes).
- A compatible carset with the desired chassis `.3do` files.

There is **one Python file**, `rend32a_multicar.py`. No assembler,
compiler, separate runtime, or other Python packages are required. No game
executables or game assets are included.

## Quick start

1. Back up your original REND32A installation and `CART.EXE`.
2. Download [`rend32a_multicar.py`](rend32a_multicar.py) to your computer.
3. In PowerShell or a command prompt, run:

   ```powershell
   python rend32a_multicar.py "C:\Games\ICR2\CART.EXE"
   ```

This creates **`CART_MULTICAR.EXE`** in the same directory, without changing
the original. By default the additional chassis list is `irl` and `panoz`.

For other chassis, explicitly list their model basenames:

```powershell
python rend32a_multicar.py "C:\Games\ICR2\CART.EXE" --chassis irl panoz lola reynard
```

Or automatically detect model names from a compatible carset:

```powershell
python rend32a_multicar.py "C:\Games\ICR2\CART.EXE" --carset-dir "C:\Games\ICR2\CARS\MYSEASON"
```

The automatic scanner needs `cars.3do` and the referenced driver wrapper
`.3do` files. It rejects unsupported carset layouts rather than guessing.
Chassis names must be DOS 8.3-compatible basenames (up to eight characters).

**To play:** Copy the generated EXE into a *separate backed-up test copy*
of the REND32A game installation, and rename that copy to `CART.EXE`.
Keep your original unchanged. The patcher does not change carset files or
create missing chassis models.

## Problems and safeguards

- **Unsupported CART.EXE:** Only the exact original REND32A executable is
  supported. Other variants, including WINDY, DOS102, and already patched
  files, are rejected using SHA-256 verification.
- **Output exists:** The script will not overwrite a generated output unless
  you specify `--overwrite`. It will never overwrite the source executable.
- **Missing chassis files:** Ensure the desired `.3do` models and their
  resources exist in the carset, and are assigned to drivers.
- **In-game problems:** Start by testing `irl` and `panoz`, then add other
  chassis incrementally. The configurable name loader, unusual views,
  replays, and all possible chassis layouts have not been validated in-game.

The original-to-C2 baseline is reconstructed using a compact embedded patch.
The script verifies both the original and resulting C2 SHA-256 hashes before
adding the chassis list. No external compiler or assembler is invoked.

The tool is an independent community modification and is not affiliated
with the game's developers or publishers. Do not redistribute proprietary
game executable files or carset assets.
