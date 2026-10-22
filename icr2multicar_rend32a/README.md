# ICR2 Multi-Car — Rendition (REND32A)

This tool modifies the **Rendition version of *IndyCar Racing II***
to support **different chassis models and independently updated wheel/tire
appearances across cars**.

It patches a copy of your own **original `CART.EXE`**, without modifying
your carset or requiring a compiler.

The author has successfully run a generated executable in-game. The
patch remains experimental across untested carsets, replay modes and
unusual chassis layouts. It is separate from the
[native Windows Multi-Car tool](../icr2multicar/).

## Requirements

- Python 3.10 or later (no third-party packages).
- The **original, unmodified REND32A `CART.EXE`** (1,109,095 bytes).
- A carset with the desired chassis `.3do` files and associated resources.

## Quick start

1. Back up the original REND32A installation and `CART.EXE`.
2. Download [`rend32a_multicar.py`](rend32a_multicar.py).
3. Open PowerShell or a command prompt and run:

   ```powershell
   python rend32a_multicar.py "C:\Games\ICR2\CART.EXE"
   ```

The tool checks your stock executable and writes
**`CART_MULTICAR.EXE`** beside it. It never overwrites the original.
The default additional chassis names are `irl` and `panoz`.

For a different selection:

```powershell
python rend32a_multicar.py "C:\Games\ICR2\CART.EXE" --chassis irl panoz lola reynard
```

To discover chassis names automatically from a supported carset:

```powershell
python rend32a_multicar.py "C:\Games\ICR2\CART.EXE" --carset-dir "C:\Games\ICR2\CARS\MYSEASON"
```

The scanner follows `cars.3do` and the driver wrapper `.3do` files.
Chassis names must use DOS 8.3-compatible basenames (up to eight
characters before `.3do`). The patcher rejects unsupported wrapper
layouts instead of guessing.

**To use the modified game:** Copy the generated EXE to a separate,
backed-up REND32A installation and rename that copy `CART.EXE`.
Make sure your chosen carset already references the matching chassis
models. The patcher does not create or assign chassis files.

## What the EXE patch changes

Compared directly with stock `CART.EXE`, the patch:

1. **Preserves each car's chassis pointer**, preventing the game from
   replacing it with a shared default geometry reference.
2. **Preloads additional `.3do` chassis models** using the game's existing
   model loader.
3. **Redirects two wheel-rendering calls** through an injected updater
   that applies each car's wheel spin, steering and front/rear tire
   appearance immediately before drawing.

It also adjusts the executable's LE header so the added routines are
mapped and a small in-game diagnostic counter area is writable.

For community reverse engineering, see the
**[complete technical reference](PATCH_TECHNICAL_REFERENCE.md)** for
original/replacement bytes, file offsets, guest addresses, injected x86
instructions, model-node fields, wheel rotation formulas and integrity
checks. It documents the changes **from stock EXE to final patched EXE**.

## Troubleshooting and limitations

- **Unsupported executable:** The script accepts only the exact stock
  REND32A `CART.EXE` version, verified by SHA-256. Other releases,
  already patched EXEs, DOS102 and WINDY are not supported.
- **Output already exists:** Choose another `--output` or use
  `--overwrite` for an existing generated file. The original input
  can never be the output.
- **Missing or unsupported chassis:** Ensure the carset includes all
  required model and texture resources. The wheel updater expects
  compatible chassis models with wheel attachments in its supported
  3DO hierarchy.
- **Game instability:** Test additional models incrementally and keep a
  clean backup. Successful in-game use does not prove compatibility
  with every carset, camera, replay or damaged-car state.

The repository distributes the patcher and its replacement-byte data,
**not** the complete original or modified game executable or commercial carsets. This independent community modification is
not affiliated with the game's original developers or publishers.
