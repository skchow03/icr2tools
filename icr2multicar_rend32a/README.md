# Configurable REND32A chassis preloader + C2 wheel animation — experimental

**Source-only community test kit, October 2026.** This folder is separate from the native Windows `icr2multicar` tool. This generates an executable from **your own** REND32A CART.EXE. It does not distribute game binaries or 3DO assets. It extends the **user-confirmed working FOUR V2 + C2 wheel fix** by substituting a configurable **preload list** for the hardcoded `irl` and `panoz` filenames. **The configurable name loader has passed static tests, but not yet been tested in DOSBox.** Do not describe it as fully working before a game test.

## Problem solved

With the validated four-model patch, additional car chassis display correctly only if their model resources are loaded in the proper Rendition context. That patch specifically preloaded `irl.3do` and `panoz.3do`. The C2 wheel patch already operates on compatible **per-car attached chassis** rather than on hardcoded model names. This tool keeps C2 unchanged while replacing the *preload* with a loop that takes any specified set of 3DO chassis basenames.

This changes the **allowed names at patch-building time**, not the set of models assigned to each driver. Your carset must already associate its drivers with the desired chassis through the usual `cars.3do` and driver-wrapper `.3do` files. You must provide all the chassis files and their resources. The utility **does not edit carset 3DOs** and **does not download or create models**.

## Inputs and reproducible baseline

1. Recommended: the byte-exact final `CART_FOUR_V2_WHEEL_BUILD_C2_ALL_CHASSIS_EXPERIMENTAL.EXE` from the C2 community kit. SHA-256:

   `cba955eab5ed03a83bebf9fa0553dca8b871e6d6405e6b5383c241a310b85be0`

   With this input, the configurable patcher uses **Python standard library only**.

2. Alternatively, the byte-exact **original, unmodified** REND32A `CART.EXE` (1,109,095 bytes). SHA-256:

   `e22effeb75105a3155212eb25d88b2e2cd127d521b72d0fa122adbd32e7a721c`

   The patcher first reconstructs C2 using the five included historical source files. This mode requires Python 3.10+ and GNU `as`, `ld`, and `objcopy` on PATH. It verifies every intermediate expected hash before adding the configurable preload.

Other game versions, already-patched variants, DOS102, and `WINDY.EXE` are **deliberately rejected**. Build a separate seasonal executable starting from the same trusted C2 input; do not recursively patch outputs.

## Usage

Create `season_1999.json` with the model names used by your intended carset:

```json
{
  "chassis": ["reynard", "lola", "penske", "swift", "dallara"]
}
```

On PowerShell, with the C2 binary in a known directory:

```powershell
python .\patch_season_chassis.py "C:\path\to\original-working-C2.EXE" --config .\season_1999.json --output .\CART_1999_C2.EXE
```

Or supply names directly:

```powershell
python .\patch_season_chassis.py "C:\path\to\original-working-C2.EXE" --chassis irl panoz reynard lola --output .\CART_mixed_C2.EXE
```

To **automatically discover** names from a supported ICR2 carset, provide the directory containing `cars.3do`, all its referenced driver `.3do` wrappers, and preferably all the referenced chassis `.3do` files:

```powershell
python .\patch_season_chassis.py "C:\path\to\original-working-C2.EXE" --carset-dir "C:\ICR2\CARS\MYSEASON" --output .\CART_MYSEASON_C2.EXE
```

The scanner follows `cars.3do` (F16 `SUPEROBJ`) through 33 or fewer driver `DYNAMIC` (F15) wrappers, then the wrapper's F04 `MATERIAL` → F14 `RECOLOR` trailing external model reference. This is the structure verified in the project's `cit74.3do` and related REND32A research. For unsupported wrapper hierarchies, it **fails rather than silently guessing**; use `--config`/`--chassis` instead. Missing `.3do` chassis assets in the scanned directory are warned about, and must be provided before starting the game.

You can combine `--config`, `--chassis`, and `--carset-dir`; the names are deduplicated. Built-in `roadcar` and `indycar` are not redundantly loaded. An item may be `lola` or `lola.3do`, case-insensitive. Each *basename* must conform to DOS **8.3 filenames** (1–8 ASCII characters before `.3do`); arbitrary filenames longer than 8 characters are not supported by this game's 3DO resource format.

The output is the same size as the original executable, with a sibling JSON manifest showing the exact model list, code size, and SHA-256. Keep the original file safe. Copy the **generated** EXE into a disposable backed-up REND32A game installation and rename that copy `CART.EXE`.

## How the patch actually works

- The original C2 wheel code is unchanged: primary hook guest `0x1AFE7`, secondary hook `0x24232`, shared wheel helper guest `0xAB390`–`0xAB6E0`, read-only trace buffer `ICW2` at guest `0xAB6E0`. C2 updates each nonselected car's F16 chassis wheel attachments immediately before drawing, including original Roadcar and Indycar.
- The FOUR V2 chassis-preservation two-byte NOP at raw `0x80ACF` remains unchanged.
- The previous FOUR V2 loader code at raw `0xE7160` remains intact but is bypassed.
- The original Roadcar preload *call site* at raw `0x50970` is redirected to a small new loader at raw `0xE7540` (guest `0xAB720`).
- This loader first performs the **original Roadcar load** (`0x6C5EC` guest/`0xA840C` raw) and preserves the original returned registers, then loops through an embedded table of requested filenames, calling that same loader once per name. The filename strings reside in the previously zero-filled mapped LE code region; code uses a position-independent `call`/`pop` lookup, without new LE fixups.
- The table has 16 bytes per filename (to fit an 8.3 name with terminating NUL). The original model preload routine occupies 76 bytes; the new loop only adds names to the existing 156 mapped code pages, extending the object-1 virtual size at raw header offset `0x6F2C` if necessary. LE code page count, code object flags, original wheel updates, and game file length remain unchanged.
- The patcher verifies exact source SHA and call signatures, confirms the target code cave is zero-filled, scans for LE relocation overlaps, preserves the critical C2 regions, and verifies its output SHA.

### Limits and risks

- **Not unlimited.** The existing mapped cave permits **up to 138 extra distinct names** in this particular binary layout. This is only a *binary patch-space maximum*, not a validated runtime resource capacity. The game's usual carset contains **33 driver slots**, so a practical season will normally need far fewer unique chassis.
- Actual available RAM, texture slots, 3DO dependency loading, render resources, and other internal engine limits may impose a much lower practical limit. **We have not verified 5+ distinct chassis live yet.** Test incrementally: the already confirmed `irl/panoz` list, then add one newly named chassis, then the rest of your season.
- Additional chassis should follow the demonstrated F16 root with wheel children 0–3 as F15 `DYNAMIC` attachments and a compatible F04/F14 driver-wrapper attachment path. Other layouts are **not** supported by the current wheel helper.
- The selected/player car and special damaged-state renderers still have distinct routines; replays, track changes, crash cases, and unusual cameras are regression targets, not proven stable.
- The C2 baseline changes executable memory permissions for a trace buffer. Retain that behavior for binary compatibility, but do not assume the modified executable is safe in every DOSBox variant. This is experimental code and should not be used with irreplaceable save data.

## ICR2Runtime diagnostics

The included `icr2runtime_wheel_monitor.py` is a read-only variant of the C2 monitor. It relies on the separately installed [ICR2Runtime v0.13](https://github.com/skchow03/icr2tools/tree/main/icr2runtime) modules (not bundled). Keep it in this `icr2multicar_rend32a` folder beside the patcher and run:

```powershell
python .\icr2runtime_wheel_monitor.py --launch --runtime-dir "..\icr2runtime" --seconds 10 --output .\wheel_season.json
```

The tool recognizes the unchanged C2 wheel hooks; changing the **preload** does not change C2's `ICW2` trace format. Its counters show renderer hits, completed wheel updates, invalid-pointer skips, and last updated car, but do not establish visible correct animation on their own.

## Static tests

```powershell
python -m unittest -v test_patch_season_chassis
```

The tests cover name sanitization and deduplication, programmatic F16/F04/F14 carset discovery, C2 SHA gating, patch signature preservation, exact table encoding, LE expansion and the fixed code-space maximum. Tests involving original game EXEs or 3DOs are skipped when the user-supplied sources are absent.

## Distribution

Only source scripts, tests, example JSON, and documentation are included in this ZIP. Each modder should build against their own copy of REND32A. Do not distribute copyrighted `CART.EXE` or commercial model assets in patch releases without permission. This patch is independent of, and not endorsed by, the original publisher.
