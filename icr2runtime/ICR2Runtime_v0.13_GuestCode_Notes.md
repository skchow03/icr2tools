# ICR2Runtime v0.13 — DOSBox guest-code patching

ICR2Runtime v0.13 adds `PATCHGUESTCODE`, a guarded code-write operation
for DOSBox's emulated ICR2 builds. This does **not** change native
`PATCHCODE` protections.

## Why this is needed

In a live REND32A/DOSBox session, the multi-chassis routine was identified
by a matching function prelude and tail. Its chassis-pointer instruction
was `89 02` at guest address `0x04998F` and mapped to Windows host
address `0x0FCF0CDF`. A read-only `VirtualQueryEx` diagnostic showed
`MEM_PRIVATE`, `MEM_COMMIT`, `PAGE_READWRITE`. v0.12's native
`PATCHCODE` rejected it because it required an executable *host* page.
This was an expected protection-policy rejection, not evidence the guest
address or instruction bytes were incorrect.

## Protocol

`PATCHGUESTCODE <pid-decimal> <guest-address-hex> <expected-hex> <replacement-hex>`

- Requires the runtime's explicit `--enable-code-writes` startup flag,
  not `--enable-data-writes`; `CAPS` then includes `PATCH_GUEST_CODE`.
- Restricted to detected DOS102 and REND32A games. WINDY101 is rejected.
- The service verifies game signature, process creation time, cached
  translation, exact expected bytes, and absence of overlapping tracked
  patches or animation leases.
- Expected and replacement bytes must have the same size, 1–8 bytes.
- The existing `patchDataBytes` writer handles host
  `PAGE_READWRITE` / `PAGE_WRITECOPY` pages with compare, write and
  read-back verification. No changes to Windows page protections.
- The resulting patch is recorded as `GUESTCODE` in `PATCHES` and is
  restored with `RESTORE <pid> <guest-address-hex>` using the same
  writable-host-page implementation.
- Native `PATCHCODE` continues to require an executable host page.

## Python integration

```python
client.patch_guest_code(pid, address, b"\x89\x02", b"\x90\x90")
# Inspect game behavior, then:
client.restore(pid, address)
```

**Discover and verify the live function signature** first. The REND32A
address `0x04998F` was observed in one session; it is not a promised
constant across installations, game revisions, or DOSBox layouts.

## Limitations and validation still required

Success from the host-memory API does not guarantee DOSBox's dynamic
recompiler discards its cached guest instructions. A live in-game
patch/restore trial is needed, ideally with multiple DOSBox CPU cores.

Writes occur while DOSBox is running. There is no guest-CPU suspension
or transactional isolation. Patches can be left behind by unexpected
runtime exits, game restarts, or conflicting tools. A failed partial write
may not be tracked; use only disposable testing sessions.

MSVC compilation, runtime protocol smoke testing, and live REND32A behavior
are not yet verified for this PR. Existing Windows-only integration tests
cover service capabilities when the built executable is supplied.

## Migration from v0.12

The named pipe is now `\\.\pipe\ICR2Runtime_v13` and the mutex is
`Local\ICR2Runtime_v13_Service`. Rebuild the C++ service and update
`icr2_client.py` and `runtime_launcher.py` from the same revision.
v0.12 clients cannot use the v0.13 endpoint. Existing wrappers must
call `patch_guest_code` rather than native `patch_code` for DOSBox.
