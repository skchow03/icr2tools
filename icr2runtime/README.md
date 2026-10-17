# ICR2Runtime

**ICR2Runtime v0.12** is an experimental, Windows-only C++ memory-access service for
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

You can start the service manually, or let any compiled Python client
start/reuse it automatically using `runtime_launcher.ensure_runtime()`.
For manual testing, launch a supported ICR2 build, keep the runtime running,
and open another terminal in the `icr2runtime` directory:

```powershell
python -c "from icr2_client import ICR2Client; c = ICR2Client(); print('Connected:', c.ping()); print(c.list_games())"
```

This is read-only and does not require any write flags.

The Python API is in [`icr2_client.py`](icr2_client.py). Use
`ICR2Client.read()`, `read_bytes()`, and `read_struct()` for small reads;
use `ICR2Session` for repeated requests on a persistent pipe connection.
Select the target game explicitly if multiple supported game instances are
running. Never hard-code process IDs or DOSBox translation bases.

## Shared startup and shutdown (v0.12)

The C++ executable is single-instance per Windows login session (named mutex
`Local\\ICR2Runtime_v12_Service`). Python tools can launch it concurrently;
the losing launch exits normally, and both clients connect to the same
`\\\\.\\pipe\\ICR2Runtime_v12` endpoint.

```python
from runtime_launcher import ensure_runtime
from icr2_client import ICR2Session

client = ensure_runtime()   # reuses an existing v0.12 service or starts read-only
print(client.status())       # version and idle/client/patch counts
print(client.list_games())

# Use a persistent connection while your GUI/dashboard is active.
with ICR2Session() as session:
    print(session.request("PING"))
```

Auto-started services use `--idle-timeout 60` by default. The service shuts
down after 60 seconds without connected clients **only if no guarded patches
or animation leases remain active**. Persistent `ICR2Session` connections
prevent idle exit. Manual launches without `--idle-timeout` stay running
until explicitly closed; `--idle-timeout 0` also disables auto-exit.
The upper limit is 3600 seconds.

```powershell
.\\build\\Release\\icr2runtime.exe --idle-timeout 60
```

For public distribution, place `icr2runtime.exe` next to each compiled Python
tool, or bundle it with PyInstaller:

```powershell
pyinstaller --onefile --windowed --add-binary "icr2runtime.exe;." mytool.py
```

When bundled in PyInstaller's temporary extraction directory, the launcher
copies the runtime to a content-addressed per-user cache under
`%LOCALAPPDATA%\\ICR2Tools\\ICR2Runtime`. This allows the shared service
to outlive the Python EXE without depending on PyInstaller temporary files.
You must include `runtime_launcher.py` and `icr2_client.py` in the Python
application (e.g. alongside its entry-point module).

The v0.12 named-pipe endpoint replaces the v0.11 endpoint. Recompile or
update Python clients to v0.12; old clients should not be mixed with the new
service. Existing v0.11 services can technically run alongside v0.12 but are
not reused by v0.12 launchers.

## Optional memory writes and safety

**Writes are disabled by default.** Enable only the capability you need:

```powershell
.\build\Debug\icr2runtime.exe --enable-data-writes
```

The separate `--enable-code-writes` flag permits guarded code patching.
A tool that explicitly needs writes can start a missing service using
`ensure_runtime(enable_data_writes=True)`; this requires an explicit
application decision or user consent. If a service is already running
read-only, the helper raises `RuntimeCapabilityError` instead of restarting
it, interrupting other clients, or silently enabling writes. The write flags
are service-wide, not per-client authorizations. An active tracked patch or
animation lease inhibits automatic idle shutdown; restoration still isn't
guaranteed after crashes or process termination.
Ordinary dashboard and telemetry readers should use neither flag.

Write operations require expected original bytes and may fail if game memory
has changed. Restoration is **not guaranteed** following an abrupt process
exit, game reload, or a conflicting modification. Test writes only in
disposable sessions and never assume addresses from one game build apply to
another. The runtime has not been production-hardened or validated for all
track-reload and multi-client scenarios.

## Documentation and integrations

See the [Developer and Integration Guide](ICR2Runtime_v0.12_Developer_Guide.md)
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
