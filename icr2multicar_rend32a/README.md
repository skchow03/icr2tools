# ICR2 Multi-Car — Rendition (REND32A)

This tool modifies the **Rendition version of *IndyCar Racing II***
to support **different chassis models and independently updated wheel/tire
appearances across cars**.

It patches a copy of your own **supported, unmodified `CART.EXE` or `INDYCAR.EXE`**, without modifying
your carset or requiring a compiler.

The author has successfully run a generated executable in-game. The
patch remains experimental across untested carsets, replay modes and
unusual chassis layouts. It is separate from the
[native Windows Multi-Car tool](../icr2multicar/).

## Requirements

- Python 3.10 or later (no third-party packages).
- One of the **five exact, verified REND32A input executables** listed below. Modified or unknown EXEs are rejected.
- A carset with the desired chassis `.3do` files and associated resources.

## Recognized executable versions

These are *exact binary fingerprints*, not loose labels. The patcher accepts the
original REND32A CART build, plus four builds reported compatible with
Sharangad's wrapper. Runtime testing of the newly added combinations remains
pending.

| Input build | Size | SHA-256 |
| --- | ---: | --- |
| Original REND32A CART | 1,109,095 | `e22effeb75105a3155212eb25d88b2e2cd127d521b72d0fa122adbd32e7a721c` |
| ICRWide (20260722001), CART | 1,109,095 | `d3329cde896725066436a20f4f67bf9c70fed59db1bc9947f3f3a5aa0d78889d` |
| ICRWide (20260722001), INDYCAR | 1,109,095 | `2a97bf1f1d04201eeef144031851a2f35f38b7309c636ad421c1084572d562c3` |
| IncreasedHeapSize, CART | 1,247,899 | `b23574535c6b38dea2a7affa43ab70a5d3d6a66d59e2ab9ddbdbd2388672a401` |
| IncreasedHeapSize, INDYCAR | 1,247,899 | `de029d70844313e7afc7e94cce6357d832ff893ede4afeb6d9fa2bf41b28e35c` |

The IncreasedHeapSize builds have an additional DOS executable prefix. Their
mapped game-code addresses match the canonical build, but their raw *file*
offsets are `0x21E34` higher. The patcher automatically translates raw
offsets and verifies a separate complete patched-image SHA-256 for each input.

## Quick start

1. Back up the original REND32A installation and `CART.EXE`.
2. Download [`rend32a_multicar.py`](rend32a_multicar.py).
3. Open PowerShell or a command prompt and run:

   ```powershell
   python rend32a_multicar.py "C:\Games\ICR2\CART.EXE"
   ```

The tool checks the entire original executable by SHA-256 and writes
**`CART_MULTICAR.EXE`** or **`INDYCAR_MULTICAR.EXE`**, depending on the input.
It never overwrites the original. The input file's name does not affect version detection.
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
backed-up REND32A installation and rename that copy `CART.EXE` or `INDYCAR.EXE`,
as appropriate.
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

- **Unsupported executable:** The script accepts only the five exact original
  builds above, verified by size and SHA-256. Other releases, already patched
  EXEs, ordinary DOS 1.0.2 and WINDY are not supported.
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

## Tests

The included `test_rend32a_multicar.py` performs source-only unit tests
without any proprietary executables:

```bash
python -m unittest discover -s icr2multicar_rend32a -p "test_*.py"
```

To check all five known executable fingerprints, core patches, and final golden
hashes, set `ICR2_REND32A_FIXTURES` to a folder with the original EXEs named
`CART(1).EXE`, `ICRWide.20260722001_CART.EXE`,
`ICRWide.20260722001_INDYCAR.EXE`,
`ICR2.IncreasedHeapSize_CART.EXE`, and
`ICR2.IncreasedHeapSize_INDYCAR.EXE`, then rerun the same test command.
Do not distribute these game binaries in the repository.

The repository distributes the patcher and its replacement-byte data,
**not** the complete original or modified game executable or commercial carsets. This independent community modification is
not affiliated with the game's original developers or publishers.
