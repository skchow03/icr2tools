# ICR2Runtime v0.12 — Developer and Integration Guide

**Baseline:** v0.12 lifecycle changes built on the validated v0.12 source (October 2026).  
**Status:** Experimental Windows service. The v0.11.x read/write validation below remains historical; v0.12 lifecycle management requires Windows build/integration testing.  
**Audience:** Future Python-tool integrations (`icr2dash`, `icr2timing`, `icr2_animator`, `icr2edit`), and C++ maintenance.

> This describes the v0.12 source and observed validation results. It is not a guarantee of production safety. Do not assume a variable's address is interchangeable among versions.

## 1. Design and architecture

`icr2runtime.exe` runs as a separate Windows process. It locates supported running ICR2 instances, holds cached read handles to their host processes, translates ICR2-version-specific Ghidra addresses into Windows host addresses, and serves named-pipe requests from other programs. The Python module `icr2_client.py` implements the current wire protocol with only the Python standard library.

```
ICR2 running in DOSBox ECE / Rendition DOSBox / native WINDY
              |
       Windows process memory
              |
       icr2runtime.exe (C++)
       game discovery, address translation,
       reads, guarded patches, animation leases
              |
       \\.\pipe\ICR2Runtime_v12
              |
       icr2_client.py (Python)
              |
      icr2dash / icr2timing / icr2edit / icr2_animator
```

**Separation of responsibilities:** The runtime supplies *memory access* and process identity, not a stable semantic telemetry model. Each client or its shared adapter supplies version-specific field addresses, data types, units, and game-state interpretation. GUI drawing, animation math, keyboard inputs, shifter logic, and display placement remain in the client applications.

## v0.12. Shared startup and service lifecycle

### Single instance and application reuse

The Windows C++ service owns a named mutex,
`Local\\ICR2Runtime_v12_Service`, throughout its lifetime. If two Python
clients start the C++ executable simultaneously, one instance acquires the
mutex and serves requests; a second returns exit code 0. Both Python callers
poll `\\\\.\\pipe\\ICR2Runtime_v12`, rather than assuming the child process
they launched must stay alive. The v0.12 pipe is deliberately distinct from
the v0.11 endpoint to avoid unversioned protocol mixing.

Import `runtime_launcher.ensure_runtime` from the application, then use
the existing Python client's read/session APIs:

```python
from runtime_launcher import ensure_runtime
from icr2_client import ICR2Session

client = ensure_runtime()  # defaults to read-only; idle timeout 60s if launched
print(client.capabilities())
print(client.status())     # e.g. version 0.12, configured idle timeout
games = client.list_games()

with ICR2Session() as session:
    # Keep this session open while a dashboard polls frequently.
    print(session.request("PING"))
```

If a shared instance is already running, its original flags and idle timeout
take precedence over the launcher's arguments. No application kills the
service at exit. Clients reconnect/relaunch after a service idle exit.

### Idle shutdown

Manual `icr2runtime.exe` launch without arguments is persistent. The
optional `--idle-timeout SECONDS` (0..3600) enables automatic shutdown;
0 disables the timer. The Python launcher uses 60 seconds by default.
Shutdown is permitted only when:

* no named-pipe connection is active (persistent sessions count as active);
* at least the configured interval has elapsed since the last client
  connection completed;
* neither tracked ordinary patches nor animation leases remain outstanding.

The runtime wakes blocked synchronous pipe-accept workers, joins the
periodic game-scanning thread and then exits. It never silently abandons
tracked changes merely because all Python clients closed. This does
**not** guarantee restoration after a crash, forced termination, or a
conflicting memory edit. A crashed writer may leave a lease outstanding
until a game process terminates or the service is explicitly stopped.

The `STATUS` command provides a single-line response such as:

```text
OK\t0.12\tIDLE_TIMEOUT=60\tACTIVE_CLIENTS=1\tTRACKED_PATCHES=0\tACTIVE_ANIMATIONS=0
```

The `LIFECYCLE_IDLE` string is advertised by `CAPS`.

### Bundling and path resolution

Use either side-by-side `icr2runtime.exe` + compiled Python application,
or PyInstaller `--add-binary "icr2runtime.exe;."` with `--onefile`.
Both `runtime_launcher.py` and `icr2_client.py` must be importable by the
Python application's entry point. In a PyInstaller onefile build the launcher
copies the binary from the temporary extraction tree to a content-addressed
cache under `%LOCALAPPDATA%\\ICR2Tools\\ICR2Runtime\\<hash>` before starting
it. This allows the runtime to outlive the application without executing
from a deleted temporary directory.

Direct launch for a write-requiring client is *explicit*:

```python
client = ensure_runtime(enable_data_writes=True)
```

That enables DATA write capabilities on a newly launched service and thus
for any local client that can reach its pipe; it is not a per-client security
grant. If an already-running service lacks the requested capability,
`RuntimeCapabilityError` is raised. It is never silently restarted,
replaced, or promoted to write-enabled. Code writes require an independent
`enable_code_writes=True` opt-in. Caller UI should ask for permission before
choosing either write-enabled mode. The existing guarded expected-byte
protocol remains in force.

### Validation

`.github/workflows/icr2runtime.yml` builds the runtime under MSVC on
Windows and exercises launcher mock tests, single-instance detection,
read-only capability reporting, named-pipe sessions and automatic idle exit.
These tests do not simulate game process memory or verify patch restoration;
those require controlled tests with recognized ICR2 game builds.

## 2. Supported game versions and addressing

| Runtime version tag | Game form | Verified signature / Ghidra reference | Address notes |
|---|---|---|---|
| `DOS102` | DOS ICR2 in DOSBox ECE | ASCII `Unable to find IndyCar.exe` at `0xA4120` | Game-relative Ghidra offsets translated into host DOSBox memory |
| `REND32A` | Rendition build in DOSBox | ASCII `RN1 Build #61` at `0xB08D9` | Game-relative Ghidra offsets translated into host DOSBox memory |
| `WINDY101` | Native Windows ICR2 | ASCII `WindyTimerPhysSemaphore\0` at `0x004F5A7C` | Ghidra virtual addresses generally already have Windows PE load basis |

The translation rule implemented by `GameMemory` is:

```
host_memory_address = game.addressTranslationBase + ghidra_address
```

**Do not add `hostModuleBase`** when calling the client read methods. `hostModuleBase` is reported for process information, not an additional adjustment to Ghidra addresses. The translation base varies between DOSBox sessions. Use `list_games()` to discover the current PID, game version, and bases; do not hard-code the PID or translation base.

**File offsets and Ghidra addresses are not equivalent.** For known supported binary regions, use `map_file_offset(pid, file_offset)` (the `MAP` command); unsupported mappings fail instead of silently guessing. The same offset in a DOS/Windows executable file may have a different runtime location.

Previously verified example locations (engine parameter data; **not** live dashboard telemetry):

| Version | EXE file offset | Corresponding Ghidra address | Known test field |
|---|---:|---:|---|
| `DOS102` | `0xF9CD8` | `0xA8884` | Ford fuel consumption |
| `REND32A` | `0xF35D4` | `0xBB7B4` | Ford fuel consumption = 6290 (u16) |
| `WINDY101` | `0xDD320` | `0x004F3B20` | Ford engine data |

These examples are for regression testing of mapping and writes, **not** for use as dashboard RPM, remaining fuel, or vehicle telemetry addresses.

## 3. Source files: what each does

| File | Role |
|---|---|
| `README.md` | Public quick start and safety notes |
| `LICENSE` | MIT license covering this runtime directory only |
| `CMakeLists.txt` | MSVC/CMake build configuration (`C++20`, `Psapi`) |
| `main.cpp` | Parses write-enable command flags and launches the service |
| `memory.h`, `memory.cpp` | Game discovery, version signatures, Ghidra-to-host translation, process read/write primitives |
| `service.h`, `service.cpp` | Named-pipe server, protocol, process registry, guards, patch/animation management |
| `icr2_client.py` | Python-facing client and persistent session interface |
| `ICR2Runtime_v0.11_Developer_Guide.md` | Integration documentation (this guide) |

Generated items such as `build/`, `__pycache__/`, and compiler intermediates are not required in a source repository. Local editor configuration in `.vscode/` is optional; review it before publishing to ensure it contains no machine-specific paths.

Keep **one** current `service.cpp`. v0.11.1 corrected a source string-literal compile error from the original v0.11 release. Do not mix older `service.cpp` versions into the active source directory.

## 4. Building and starting on Windows

Build on Windows using an MSVC C++20 toolchain and CMake. From the **ICR2Tools repository root**, change into the `icr2runtime` subdirectory first (or open that subdirectory directly in your developer shell):

```powershell
cd icr2runtime
cmake -S . -B build
cmake --build build --config Debug
```

Then start the service from the `icr2runtime` directory:

```powershell
.\build\Debug\icr2runtime.exe
```

The executable location can differ with the CMake generator and build configuration.

Read-only is the default. To enable **data** changes (including animations) for an explicitly disposable test session:

```powershell
.\build\Debug\icr2runtime.exe --enable-data-writes
```

To permit guarded **executable-code** patches, use `--enable-code-writes` (separately gated; do not enable it for a dashboard). No write flag is required for `icr2dash` or `icr2timing`.

The service uses pipe `\\.\pipe\ICR2Runtime_v12`. It refreshes discovered games approximately every 30 seconds, and `refresh()` can force a rescan. The service supports up to eight concurrent named-pipe workers. `ICR2Session` is a persistent connection and is **not thread-safe**; give each concurrent client thread its own session or serialize requests.

**Connectivity check:** Start a supported game and the read-only service, then use `ICR2Client().ping()` and `ICR2Client().list_games()` as shown below. No separate test script is required for normal use. When writes are disabled, `ANIM_BEGIN` and related capabilities are not advertised; that is expected.

## 5. Python client API

Import the supplied `icr2_client.py` from the same project or Python import path.

```python
from icr2_client import ICR2Client, ICR2Session

client = ICR2Client()
assert client.ping()
games = client.list_games()
if not games:
    raise RuntimeError("No recognized ICR2 instance")
game = games[0]  # Select explicitly if more than one instance exists
print(game.pid, game.version, hex(game.translation_base))

# Address below is ONLY an example of a verified REND32A engine table.
if game.version == "REND32A":
    data = client.read_bytes(game.pid, 0xBB7B4, 24)
    print(data.hex(" "))
```

Read-only methods:

- `capabilities() -> set[str]`: capability names enabled in the service.
- `ping() -> bool` and `refresh() -> None`.
- `list_games() -> list[Game]`: `.pid`, `.version`, `.translation_base`, `.host_module_base`, `.window_title`.
- `read(pid, ghidra_address, kind='i32')`: kinds `u8, i8, u16, i16, u32, i32, u64, i64, f32, f64`.
- `read_bytes(pid, ghidra_address, size)`: binary bulk read of **1–65,536 bytes**.
- `read_struct(pid, ghidra_address, fmt)`: Python `struct` format, e.g. `'<ii'`.
- `scan(pid, start, length, pattern, limit=64)`: exact-byte scan, pattern **1–32 bytes**, span **1–16 MiB**, max **256 matches**.
- `map_file_offset(pid, offset)`: translates validated regions of the game executable's file layout into Ghidra addresses.

Read-only client example for repeated telemetry polling, once addresses are validated:

```python
from icr2_client import ICR2Client, ICR2Session

c = ICR2Client()
selected = next(g for g in c.list_games() if g.version == "REND32A")
with ICR2Session() as session:
    # Replace these placeholders with independently VERIFIED live telemetry offsets.
    # packet = session.read_bytes(selected.pid, verified_address, verified_length)
    print(session.request("PING").strip())
```

**Important:** The `read()` and `scan()` convenience methods on `ICR2Client` open a pipe per request; `ICR2Session` allows multiple requests on one connection. Choose a long-lived `ICR2Session` for a frequently polled dashboard and decode the values client-side.

### Write APIs (opt-in and guarded)

| Python method | Behavior |
|---|---|
| `patch_data(pid, address, expected, new)` | Guarded 1–8-byte data patch |
| `patch_code(pid, address, expected, new)` | Guarded 1–8-byte code patch with separate code-write opt-in |
| `patch_batch(pid, [(address, expected, new), ...])` | Up to 32 guarded data patches, best-effort rollback if a batch fails |
| `patch24(pid, address, expected24, replacement24)` | Guarded 24-byte data record, tracked for later restoration |
| `patch_object6(pid, address, expected6, replacement6)` | Six signed little-endian `i32`s via `PATCH24` |
| `restore(pid, address)` | Restore a tracked ordinary patch |
| `list_patches()` | List active tracked patches |
| `session.anim_begin(pid, address, original24)` | Reserve and verify original 24-byte record |
| `session.anim_update(pid, address, new24)` | Compare with last frame and update same record |
| `session.anim_end(pid, address)` | Verify previous frame and attempt original-byte restoration |

`ANIM_LIST` exists in the service wire protocol for diagnostics. No demonstrated stable convenience method is provided by `ICR2Client` for it; call `session.request("ANIM_LIST")` if needed.

The animation lease persists after a client disconnects. **The client must explicitly call `anim_end()`**, including when stopping due to an exception, but a crash can prevent cleanup. There is no reliable track-reload invalidation inside an unchanged host process and no per-Python-client ownership model in this version. Writes are guarded, not CPU-atomic.

## 6. Wire protocol (when integrating a non-Python client)

**Pipe:** `\\.\pipe\ICR2Runtime_v12`. Requests are single ASCII lines terminated by newline. Most successful replies begin `OK\t`; failures begin `ERR\t` with a machine-readable error name. Addresses are **hexadecimal Ghidra addresses**; PIDs and lengths are **decimal** unless explicitly noted. The Python client provides canonical encoding examples.

Examples of command formats (do not include angle brackets literally):

```
PING
CAPS
LIST
REFRESH
READ <pid> <addrHex> <u8|i8|u16|i16|u32|i32|u64|i64|f32|f64>
BULK <pid> <addrHex> <lengthDecimal>
MAP <pid> <fileOffsetHex>
SCAN <pid> <startHex> <lengthDecimal> <patternHex> <limitDecimal>
PATCH <pid> <addrHex> <expectedHex> <replacementHex>
PATCHCODE <pid> <addrHex> <expectedHex> <replacementHex>
PATCHBATCH <pid> <countDecimal> <addrHex:expectedHex:replacementHex> ...
PATCH24 <pid> <addrHex> <expected48HexChars> <new48HexChars>
PATCHES
RESTORE <pid> <addrHex>
ANIM_BEGIN <pid> <addrHex> <original48HexChars>
ANIM_UPDATE <pid> <addrHex> <current48HexChars>
ANIM_END <pid> <addrHex>
ANIM_LIST
```

**Persistent sessions:** The first line is `SESSION`; thereafter the server uses framed replies rather than the one-request-per-connection EOF convention. `ICR2Session` implements the framing and should be preferred to hand-parsing it. Ordinary `request()` opens/closes a new connection.

**Capabilities are conditional:** `PATCH_DATA`, `PATCHBATCH`, `PATCH24`, and `ANIM_*` are exposed only when `--enable-data-writes` is active. `PATCH_CODE` requires its own flag. `PATCH24_READINESS` is a baseline capability advertised even when writes are disabled; it **does not mean permission to write**.

## 7. Verified tests and their boundaries

| Test / platform | Observed result | What it establishes |
|---|---|---|
| v0.9 REND32A | Exact signature found via bounded `SCAN`; guard failure cases rejected | Scan and safety checks in known region |
| v0.8 REND32A | Two engine parameters `6290→6291` and `6500→6501`; restoration succeeded | Guarded batch write and mapping |
| v0.7 WINDY101 | `0x0045B719: 89 02 → 90 90 → 89 02` | Guarded code write and restore |
| v0.10 REND32A | 24-byte engine record patch and byte-for-byte restore | Whole-record `PATCH24` behavior |
| v0.11 REND32A read-only | One game detected; pipe `PING`; animation disabled | Build, discovery, and read-only protocol |
| v0.11 REND32A animation | 60 updates/2.000s at 30 Hz; 120 updates/2.454s at requested 60 Hz (48.9/s); original 24 bytes restored | Leases, repeated writes, and cleanup on disposable engine data |

**Not yet demonstrated in the documented validation:** running the real Python animator against live trackside object records; reliable handling of a track reload without a process restart; dashboard-specific telemetry addresses; sustained multi-object animation; simultaneous overlapping client workflows.

The 48.9/s result applies to the measured write test; it is **not** a measured limit on read-only dashboard polling.

## 8. How to integrate Python tools

**ICR2Dash:** Keep PyQt rendering and gear-handler input logic. Implement a new read-only telemetry provider that calls `ICR2Client`/`ICR2Session`; pass the same `(rpm, boost, temp, fuel, mph, gear, f_rollbar, r_rollbar, brake, boost_knob, laptime)` contract that `dashboard_reader.read_dashboard()` currently returns. Locate live data fields independently for `DOS102`, `REND32A`, `WINDY101`, document data types and scaling, and preserve screenshot decoding as a temporary fallback. No C++ runtime change is currently required by this architecture. The runtime currently does not report whether the cockpit view is visible or where the overlay should be positioned; keep existing window/pixel detection unless separate fields are found.

**ICR2Timing:** Swap direct DOSBox host-memory reads for runtime typed/bulk reads; preserve timing formulas. Verify every address and scale for each version before claiming cross-version parity.

**ICR2Edit:** Do not send CSV executable **file** offsets directly to `read`/`patch`. Convert supported mappings via `MAP` or a documented per-build address map; preserve guarded expected bytes and restoration semantics.

**ICR2 Animator:** Match object coordinates (3 x signed i32) with scan, obtain and snapshot complete 24-byte records (6 x signed i32), then register an animation lease; use `ICR2Session` for updates and always end a lease during orderly shutdown. Stop and re-resolve objects after track load/reload; this is a client safeguard until runtime detection is improved.

**Telemetry address map proposal:** Keep a Python or CSV map outside the runtime, with fields `version,field,ghidra_address,type,scale,units,source,verified_date`. Never promote an inferred offset to "verified" until confirmed against live ICR2 behavior.

## 9. Source control and public distribution

**Recommended repository contents:**

```
icr2runtime/
  README.md
  LICENSE
  CMakeLists.txt
  main.cpp
  memory.cpp
  memory.h
  service.cpp
  service.h
  icr2_client.py
  ICR2Runtime_v0.11_Developer_Guide.md
```

`README.md` provides the project overview and links to this guide. The MIT license in `icr2runtime/LICENSE` is proposed for this runtime directory only; it does **not** automatically license the rest of `icr2tools` or proprietary game assets. Keep build outputs and machine-generated files out of version control. A typical `.gitignore` should exclude `build/`, `__pycache__/`, `*.pyc`, `*.ilk`, and compiled binaries/debug artifacts such as `*.exe` and `*.pdb`, unless releases intentionally distribute binaries separately.

**Before publishing:** Review any optional `.vscode/` settings, launch profiles, example configuration files, and commit history for absolute paths, usernames, credentials, or environment-specific details. Documentation and code should use relative paths and generic examples. The source repository need not include prior development test scripts; the historical validation results in section 7 are retained as a record of observed behavior.

## 10. Next changes only if justified

The v0.11.1 service appears sufficient for initial read-only `icr2dash` telemetry integration. New C++ features should be motivated by a measured missing capability, not merely by adding a new Python consumer. Candidate future improvements: same-process track reload detection; client ownership/lease cleanup; telemetry snapshot consistency; read-performance instrumentation; production-grade service lifecycle management.

**Maintenance rule:** When changing protocol names, address translation, game version detection, safety behavior, or Python method signatures, update this guide and any maintained regression checks *in the same change*. Keep tested versus hypothetical features clearly labeled.
