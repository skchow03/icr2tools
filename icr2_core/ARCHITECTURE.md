# icr2_core Architecture

`icr2_core` is the shared library that powers the live overlay and tooling. It
wraps low-level process memory, exposes immutable telemetry models, and ships
lightweight file parsers so GUI apps can stay thin.

## Responsibilities
- **Memory access** – `icr2_memory.ICR2Memory` attaches to DOSBox/ICR2 by window
title keywords and signature bytes, exposes typed `read`/`write` helpers, bulk
readers, and cleans up Win32 handles automatically.
- **Telemetry decoding** – `reader.MemoryReader` pulls raw counts, names, and
car-state blobs from `ICR2Memory`, computes derived lap/interval fields, and
returns frozen `RaceState` snapshots built from `model.py` dataclasses.
- **Models** – `model.Driver`, `model.CarState`, and `model.RaceState` are
simple, immutable carriers designed to be passed safely across threads/UI
boundaries.
- **DAT/TRK helpers** – `dat/` can unpack or repack `.DAT` archives; `trk/`
parses `.TRK` geometry, builds surface meshes, samples centrelines, and exports
3D/OBJ data for overlays or the track viewer.
- **Camera helpers** – `cam/` reads and writes `.CAM` files plus TV segment
ranges so editors can modify camera placement without reimplementing codecs.

## Data flow
1. **Attach** – UI code instantiates `ICR2Memory`, which finds the DOSBox/ICR2
process, signature-scans the executable to derive the base address, and prepares
per-version offsets from `settings.ini`.
2. **Read** – `MemoryReader.read_race_state()` calls `ICR2Memory.read()` or
`bulk_read` helpers to fetch counts, names, numbers, and the 0x214 telemetry
block for each car.
3. **Derive** – `MemoryReader` computes laps completed, last-lap validity,
intervals, pit/retirement state, and track metadata, then builds immutable model
instances.
4. **Consume** – Callers (the timing overlay, track viewer, or tests) receive a
`RaceState` that can be rendered, logged, or exported without touching process
memory again.

## Key modules
- **`icr2_memory.py`** – Win32 process discovery, signature scanning, typed
reads/writes, bulk reads, and context-managed cleanup.
- **`reader.py`** – Telemetry parsing, lap/interval math, track metadata lookup,
and error handling that guards against partial reads.
- **`model.py`** – Frozen dataclasses for drivers, car states, and the overall
race snapshot.
- **`dat/`** – `unpackdat.py` extracts DAT contents; `packdat.py` rebuilds
archives from `packlist.txt` definitions.
- **`trk/`** – `track_loader.py` reads TRK sections; `trk_utils.py` samples
centrelines and coordinates; `surface_mesh.py` builds ground-surface strips;
`trk_exporter.py` and `trk23d.py` serialize geometry for external tools.
