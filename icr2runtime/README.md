# ICR2Runtime

**ICR2Runtime** is an experimental, Windows-only C++ memory-access service for
*IndyCar Racing II* (ICR2). It detects supported running game builds and exposes
memory reads, bounded searches, optional guarded patches, and 24-byte animation
record updates through a local Windows named pipe.

This directory is part of [ICR2Tools](../README.md). It is not a standalone
game, a replacement executable, or a general-purpose DOSBox plugin.

## Supported game builds

| Runtime identifier | Game environment |
| --- | --- |
| `DOS102` | DOS ICR2 v1.0.2 in supported DOSBox configurations |
| `REND32A` | Rendition ICR2 build in DOSBox |
| `WINDY101` | Native Windows ICR2 (WINDY) |

Detection depends on exact signatures. Support for other game revisions or
DOSBox variants is not guaranteed. Runtime addresses are *Ghidra addresses for
the detected build*, not executable file offsets or arbitrary host-process
addresses.

## Build on Windows

Requirements: **Windows**, **CMake 3.20+**, and an **MSVC C++20 toolchain**
(such as Visual Studio 2022 with Desktop development with C++). The supplied
Python client uses the Windows standard library APIs through `ctypes`; no
third-party Python dependencies are required for that client.

From the ICR2Tools repository root, use a developer terminal with MSVC
available:

```powershell
cd icr2runtime
cmake -S . -B build
cmake --build build --config Debug
.\build\Debug\icr2runtime.exe
```

The executable location may differ with your CMake generator and configuration.

## Connect from Python

Launch a supported ICR2 build, keep the runtime running, and open another
terminal in the `icr2runtime` directory:

```powershell
python -c "from icr2_client import ICR2Client; c = ICR2Client(); print('Connected:', c.ping()); print(c.list_games())"
```

This is read-only and does not require any write flags.

The Python API is in [`icr2_client.py`](icr2_client.py). Use
`ICR2Client.read()`, `read_bytes()`, and `read_struct()` for small reads;
use `ICR2Session` for repeated requests on a persistent pipe connection.
Select the target game explicitly if multiple supported game instances are
running. Never hard-code process IDs or DOSBox translation bases.

## Optional memory writes and safety

**Writes are disabled by default.** Enable only the capability you need:

```powershell
.\build\Debug\icr2runtime.exe --enable-data-writes
```

The separate `--enable-code-writes` flag permits guarded code patching.
Ordinary dashboard and telemetry readers should use neither flag.

Write operations require expected original bytes and may fail if game memory
has changed. Restoration is **not guaranteed** following an abrupt process
exit, game reload, or a conflicting modification. Test writes only in
disposable sessions and never assume addresses from one game build apply to
another. The runtime has not been production-hardened or validated for all
track-reload and multi-client scenarios.

## Documentation and integrations

See the [Developer and Integration Guide](ICR2Runtime_v0.11_Developer_Guide.md)
for exact version signatures, address-translation rules, protocol commands,
Python integration, previous validation results, and known limitations.

The service is intended to be reusable by Python tools such as ICR2Timing,
ICR2Dash, ICR2Edit, and ICR2 Animator. The runtime provides raw memory access;
each tool must supply and validate its own semantic telemetry/address map.

## License

The contents of this **`icr2runtime/` directory** are provided under the
[MIT License](LICENSE). This directory-scoped license does not apply to other
ICR2Tools directories or to proprietary ICR2 game files. No game assets or
game executables are included in this component.

ICR2Runtime is an independent modding project and is not affiliated with the
game's original publisher or developers.
