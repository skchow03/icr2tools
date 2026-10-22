# ICR2 Multi-Car — Rendition (REND32A)

This tool modifies the **Rendition version of *IndyCar Racing II***
to support **different chassis models and independently updated wheel/tire
appearances across cars**.

It patches a copy of your own **supported REND32A `CART.EXE`**, without modifying
your carset or requiring a compiler.

The author has successfully run a generated executable in-game. The
patch remains experimental across untested carsets, replay modes and
unusual chassis layouts. It is separate from the
[native Windows Multi-Car tool](../icr2multicar/).

## Requirements

- Python 3.10 or later (no third-party packages).
- A **supported REND32A `CART.EXE`** (1,109,095 bytes): the original
  release, or the exact recognized modified variant described below.
- A carset with the desired chassis `.3do` files and associated resources.

## Quick start

1. Back up the original REND32A installation and `CART.EXE`.
2. Download [`rend32a_multicar.py`](rend32a_multicar.py).
3. Open PowerShell or a command prompt and run:

   ```powershell
   python rend32a_multicar.py "C:\Games\ICR2\CART.EXE"
   ```

The tool checks your input executable and writes
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

## Supported REND32A executable variants

| Input | SHA-256 | Testing |
| --- | --- | --- |
| Original stock CART.EXE | `e22effeb75105a3155212eb25d88b2e2cd127d521b72d0fa122adbd32e7a721c` | Multi-Car reported working in-game |
| Known modified CART.EXE | `14385142e4f0b99541f018c1f20eccd854fd17103da0dfddd81472520f9c3360` | **Combined Multi-Car output not yet tested in-game** |

The alternate file differs from the original by 31 bytes in 10 regions.
They include a fourfold-repeated value changed from 2,600,000 to
83,200,000, an indexed table read in game code and several other
numeric modifications. None of these bytes conflicts with the
Multi-Car changes.

For the modified input, the script verifies the **exact full-file hash**,
temporarily reconstructs the known stock bytes in memory to run its
verified patch process, and restores **all 31 of the variant's
differences** to the output. The original source EXE is never written.
It refuses other variants. This is a narrowly supported experimental
input, not a guarantee of runtime compatibility.

## Troubleshooting and limitations

- **Unsupported executable:** Only the two checksums listed below are
  accepted. Other EXEs, previously Multi-Car-patched EXEs, DOS102 and
  WINDY are rejected. Do not bypass checksum validation.
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
