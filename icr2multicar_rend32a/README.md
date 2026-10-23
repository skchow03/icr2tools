# ICR2 Multi-Car — Rendition (REND32A)

This tool modifies the **Rendition version of *IndyCar Racing II***
to support **different chassis models and independently updated wheel/tire
appearances across cars**.

It patches a copy of your own **supported, unmodified `CART.EXE` or `INDYCAR.EXE`**, without modifying
your carset or requiring a compiler.

The IncreasedHeapSize CART and INDYCAR builds have user-reported successful
in-game operation with Sharangad's Rendition wrapper. Broader testing across
carsets, replay modes and unusual chassis layouts remains pending. It is separate from the
[native Windows Multi-Car tool](../icr2multicar/).

## Requirements

- Python 3.10 or later (no third-party packages).
- One of the **two exact, unmodified IncreasedHeapSize REND32A executables** listed below. Modified or unknown EXEs are rejected.
- A carset with the desired chassis `.3do` files and associated resources.

## Recognized executable versions

The patcher deliberately accepts only these two exact binary fingerprints.
Both have been reported working in-game with the Rendition wrapper.

| Input build | Size | SHA-256 |
| --- | ---: | --- |
| IncreasedHeapSize CART | 1,247,899 | `b23574535c6b38dea2a7affa43ab70a5d3d6a66d59e2ab9ddbdbd2388672a401` |
| IncreasedHeapSize INDYCAR | 1,247,899 | `de029d70844313e7afc7e94cce6357d832ff893ede4afeb6d9fa2bf41b28e35c` |

**Not supported:** original stock REND32A CART, either ICRWide widescreen
executable, ordinary DOS 1.0.2, WINDY, and any already-patched EXE.
ICRWide's 3D viewport regression is triggered by the expanded LE code-object
virtual size; simply restoring that size makes the injected routines
inaccessible and crashes. The original stock REND32A build is excluded at
the user's request; this is a support policy, not proof that stock is unstable.

The two supported builds contain a larger DOS executable prefix. Their
mapped game-code addresses match the canonical reference layout, but their
raw *file* offsets are `0x21E34` higher. The patcher translates raw offsets
and verifies a separate full-image SHA-256 checkpoint for each supported input.

## Quick start

1. Back up the original IncreasedHeapSize installation and game executable.
2. Download [`rend32a_multicar.py`](rend32a_multicar.py).
3. Open PowerShell or a command prompt and run:

   ```powershell
   python rend32a_multicar.py "C:\Games\ICR2\ICR2.IncreasedHeapSize_CART.EXE"
   ```

The tool checks the entire original executable by SHA-256 and writes
**`CART_MULTICAR.EXE`** or **`INDYCAR_MULTICAR.EXE`**, depending on the input.
It never overwrites the original. The input file's name does not affect version detection.
The default additional chassis names are `irl` and `panoz`.

For a different selection:

```powershell
python rend32a_multicar.py "C:\Games\ICR2\ICR2.IncreasedHeapSize_CART.EXE" --chassis irl panoz lola reynard
```

To discover chassis names automatically from a supported carset:

```powershell
python rend32a_multicar.py "C:\Games\ICR2\ICR2.IncreasedHeapSize_CART.EXE" --carset-dir "C:\Games\ICR2\CARS\MYSEASON"
```

The scanner follows `cars.3do` and the driver wrapper `.3do` files.
Chassis names must use DOS 8.3-compatible basenames (up to eight
characters before `.3do`). The patcher rejects unsupported wrapper
layouts instead of guessing.

**To use the modified game:** Copy the generated EXE to a separate,
backed-up IncreasedHeapSize installation and rename that copy `CART.EXE` or `INDYCAR.EXE`,
as appropriate.
Make sure your chosen carset already references the matching chassis
models. The patcher does not create or assign chassis files.

## What the EXE patch changes

Compared with the corresponding unmodified IncreasedHeapSize executable, the patch:

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
checks. It documents changes using a canonical stock-code offset reference plus
an explicit `0x21E34` translation for the supported IncreasedHeapSize inputs.

## Troubleshooting and limitations

- **Unsupported executable:** The script accepts only the two IncreasedHeapSize
  builds above, verified by size and SHA-256. Stock REND32A, ICRWide,
  ordinary DOS 1.0.2, WINDY, and previously patched EXEs are rejected.
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

To verify the two supported full-file input fingerprints, core patch images,
and output golden hashes, set `ICR2_REND32A_FIXTURES` to a folder containing
the **original, unmodified** files named
`ICR2.IncreasedHeapSize_CART.EXE` and
`ICR2.IncreasedHeapSize_INDYCAR.EXE`, then rerun the tests. An optional
negative test also rejects stock CART and ICRWide files if those
additional originals are present. No proprietary executables are
distributed in the repository.

The repository distributes the patcher and its replacement-byte data,
**not** the complete original or modified game executable or commercial carsets. This independent community modification is
not affiliated with the game's original developers or publishers.
