# ICR2Runtime

**ICR2Runtime v0.13** is a Windows-only C++ service that gives modding tools
controlled access to the memory of supported *IndyCar Racing II* (ICR2)
processes. It supports process discovery, memory reads, address translation,
bounded searches, guarded patches, and 24-byte animation record updates.

ICR2Runtime is a component of [ICR2Tools](../README.md), not a replacement
game executable or a standalone DOSBox plugin. Its Python interface uses
only the standard library.

## Supported games

| Game identifier | Environment |
| --- | --- |
| `DOS102` | DOS ICR2 v1.0.2 in supported DOSBox configurations |
| `REND32A` | Rendition ICR2 in supported DOSBox configurations |
| `WINDY101` | Native Windows ICR2 v1.0.1 |

Game detection relies on exact binary signatures. Other game revisions and
DOSBox configurations are not guaranteed to work.

## Download a prebuilt Windows executable

Download the `ICR2Runtime-v0.13-win64.zip` asset from
[ICR2Tools Releases](https://github.com/skchow03/icr2tools/releases/tag/icr2runtime-v0.13)
once the Windows binary has been published. The ZIP contains the compiled
`icr2runtime.exe`, matching `icr2_client.py` and `runtime_launcher.py`,
this README, and the MIT license. Windows users do **not** need to install
CMake or a C++ compiler to use a release binary.

Extract the ZIP and keep the EXE alongside the matching Python files. The
runtime is normally started automatically by tools that use the shared
`runtime_launcher.py`, or it can be launched manually with
`icr2runtime.exe --enable-code-writes` when a tool explicitly needs code
patching. Python-based tools still require Python unless separately
packaged into an executable.

To publish a compiled ZIP for an existing release, maintainers can open
[GitHub Actions](https://github.com/skchow03/icr2tools/actions/workflows/icr2runtime-release.yml),
select **Publish ICR2Runtime Windows Binary → Run workflow**, and enter
the published tag (for example, `icr2runtime-v0.13`). For future runtime
releases, publishing a tag beginning with `icr2runtime-v` triggers this
workflow automatically. The workflow builds from the release tag and
uploads the ZIP only after successful tests.

## Build and start on Windows

To build from source, install **CMake 3.20+** and an **MSVC C++20 toolchain**
(for example, Visual Studio 2022 with Desktop development with C++).
From the ICR2Tools repository root:

```powershell
cmake -S icr2runtime -B icr2runtime/build -A x64
cmake --build icr2runtime/build --config Release
.\icr2runtime\build\Release\icr2runtime.exe
```

The final EXE location can depend on the CMake generator. A compiled runtime
must match the supplied `icr2_client.py` and `runtime_launcher.py`. The
source repository does not include a prebuilt executable.

**Reads are enabled by default; writes are disabled.** To opt in to guarded
code patches or writable data patches, start the service with the relevant
flag:

```powershell
.\icr2runtime\build\Release\icr2runtime.exe --enable-code-writes
# Or, for data patches and animation updates:
.\icr2runtime\build\Release\icr2runtime.exe --enable-data-writes
```

Both flags can be supplied when a tool explicitly requires both kinds of
writes. These permissions apply to the shared service, not to an individual
client. Do not enable writes for tools that only need telemetry.

## Connect from Python

Start one of the supported games and ICR2Runtime, then run Python from the
`icr2runtime` directory:

```python
from icr2_client import ICR2Client, ICR2Session

client = ICR2Client()
assert client.ping()
print(client.status())       # Includes runtime version and active patch counts
games = client.list_games()
print(games)                 # PID, game build, address bases, window title

# Reuse a pipe connection for frequently updated telemetry.
with ICR2Session() as session:
    print(session.request("PING").strip())
```

Alternatively, applications can import `ensure_runtime` from
`runtime_launcher.py`. It reuses the current shared service, or starts a
missing one with a default 60-second idle timeout:

```python
from runtime_launcher import ensure_runtime

client = ensure_runtime()  # Read-only unless explicitly requested otherwise
print(client.list_games())

# For applications that explicitly require guarded code writes:
# client = ensure_runtime(enable_code_writes=True)
```

The launcher never silently upgrades an existing read-only service to
write-enabled. If its capabilities are insufficient, it raises
`RuntimeCapabilityError`. Applications that supply their own bundled runtime
can pass `runtime_path=` to `ensure_runtime()`.

## Addresses and game detection

Runtime addresses passed to the client are **Ghidra virtual addresses for
the detected game build**, not raw executable file offsets or Windows host
process addresses.

```text
Windows host address = detected translation base + Ghidra address
```

`list_games()` returns a game identifier, PID, translation base, host module
base and window title. **Do not additionally add the host module base**, and
do not assume translation bases are unchanged across sessions. Use
`map_file_offset(pid, file_offset)` only for mapped, validated file regions;
unsupported mappings fail rather than guess.

The runtime provides memory access, **not** a universal telemetry address
map. Each consuming tool must validate its addresses, types, scales, and
meaning separately for each game build.

## Python API

`ICR2Client` offers these read and discovery operations:

| Method | Purpose |
| --- | --- |
| `ping()`, `status()`, `capabilities()` | Connectivity and service information |
| `list_games()`, `refresh()` | Discover or rescan supported processes |
| `read(pid, address, kind="i32")` | Read a typed numeric value |
| `read_bytes(pid, address, size)` | Read 1–65,536 bytes |
| `read_struct(pid, address, fmt)` | Decode a packed Python `struct` |
| `scan(pid, start, length, pattern, limit=64)` | Search for an exact byte sequence |
| `map_file_offset(pid, offset)` | Translate a verified game file offset |

Supported `read()` types are `u8`, `i8`, `u16`, `i16`, `u32`, `i32`,
`u64`, `i64`, `f32`, and `f64`. Scans accept 1–32-byte patterns,
spans up to 16 MiB, and a limit of up to 256 matches.

Write methods require exact original bytes, matching replacement lengths,
and the appropriate startup flag:

| Method | Purpose |
| --- | --- |
| `patch_data(pid, address, expected, new)` | Guarded 1–8-byte data patch |
| `patch_code(pid, address, expected, new)` | Guarded native executable-code patch |
| `patch_guest_code(pid, address, expected, new)` | Guarded DOSBox guest-code patch |
| `patch_batch(pid, patches)` | Up to 32 guarded data patches; best-effort rollback on error |
| `patch24(pid, address, expected, new)` | Guarded 24-byte data record patch |
| `patch_object6(pid, address, expected, new)` | Six signed 32-bit object fields |
| `list_patches()`, `restore(pid, address)` | Inspect and restore tracked patches |
| `anim_begin()`, `anim_update()`, `anim_end()` | Manage 24-byte animation leases |

Animation methods are available on `ICR2Session`; each uses a PID, address
and the corresponding 24-byte record (except `anim_end`, which needs no
record argument). Keep a persistent session open for repeated updates. A
session must not be shared between threads without synchronization.

### Native code and DOSBox guest-code writes

`PATCHCODE` patches native executable pages, including supported WINDY101
code. `PATCHGUESTCODE` patches verified DOSBox guest instructions for
`DOS102` and `REND32A`; it is **not** accepted for WINDY101. Both operations
require `--enable-code-writes` and accept 1–8-byte expected/replacement
pairs. The runtime verifies process identity, instruction bytes, and patch
overlaps, then tracks the changes for `RESTORE`.

DOSBox guest instructions can be stored in ordinary writable host pages.
The guest-code operation handles those pages without changing their
protection. However, a successful host-memory write does **not** establish
that DOSBox has invalidated any cached, recompiled instructions. Live
guest-code execution and restoration still require controlled validation.

### Shared service lifecycle

The v0.13 service uses:

- Pipe: `\\.\pipe\ICR2Runtime_v13`
- Mutex: `Local\ICR2Runtime_v13_Service`

Only one service instance serves the current endpoint. The launcher can be
called by multiple applications concurrently; they connect to the same
service. A manually started service runs until closed unless
`--idle-timeout SECONDS` is provided. Valid timeouts are 0–3600 seconds;
0 disables automatic shutdown.

The service exits after its idle interval only when there are **no active
clients, tracked patches or animation leases**. A persistent
`ICR2Session` prevents idle exit. Existing instances retain their original
permissions and timeout. The service periodically refreshes process
detection; `refresh()` triggers an immediate rescan.

### Wire protocol

Non-Python clients may use the local named pipe directly. Commands are
newline-terminated ASCII; successful responses begin with `OK\t`, and
errors with `ERR\t`. PIDs and sizes are decimal, while addresses are
hexadecimal. The primary commands are:

```text
PING                  STATUS                 CAPS
LIST                  REFRESH                READ
BULK                  MAP                    SCAN
PATCH                 PATCHCODE              PATCHGUESTCODE
PATCHBATCH            PATCH24                PATCHES
RESTORE               ANIM_BEGIN             ANIM_UPDATE
ANIM_END              ANIM_LIST              PATCH24_READINESS
```

The `SESSION` handshake switches to length-framed responses for multiple
requests on one connection. Prefer the provided `ICR2Client` and
`ICR2Session` modules over hand-encoding commands and frames.

## Integration and safety

Clients should choose the target game by its reported identifier and PID,
verify expected bytes before patching, and keep each tool's semantic memory
addresses separate from the generic runtime. For example, an editor with
raw EXE offsets should translate them with `MAP` before reading or writing
memory, rather than passing file offsets as Ghidra addresses.

Guarded writes are not transactional with the game's CPU. Restoration can
fail after a game reload, process termination, conflicting memory tool, or
abrupt shutdown. Animation leases require an explicit `anim_end()` to restore
the original record; a crash can prevent this. Track reload handling,
simultaneous writers, and sustained live animation workloads are not fully
validated. Test modifications with disposable game sessions.

For Python application bundles, include the matching runtime EXE,
`icr2_client.py`, and `runtime_launcher.py`. The launcher supports
PyInstaller's `--add-binary "icr2runtime.exe;."` configuration and can
cache the embedded service under
`%LOCALAPPDATA%\ICR2Tools\ICR2Runtime\<content-hash>` so it can outlive
the application's temporary extraction directory.

## Development and tests

The Windows GitHub Actions workflow builds the runtime with MSVC and runs
the Python launcher and named-pipe integration tests. From a Windows
developer machine with a compiled runtime:

```powershell
python -m unittest discover -s icr2runtime/tests -p "test_*.py" -v
```

The automated checks cover startup, client capabilities, named-pipe
behavior and idle lifecycle, **not** live patch behavior in a running ICR2
session. Keep game-specific acceptance tests separate from basic service
integration tests.

## License

The contents of **`icr2runtime/`** are available under the
[MIT License](LICENSE). This directory-scoped license does not cover
other ICR2Tools components or proprietary game files. No game executable
or game assets are distributed with ICR2Runtime.

ICR2Runtime is an independent community modding project, unaffiliated
with the game's original developers or publishers.
