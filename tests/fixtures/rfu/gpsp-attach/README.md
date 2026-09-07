# Attach-only gpSP qualification homebrew

This original test program uses MIT-licensed gba-link-connection at the exact
commit in `provenance.json`. Startup/linker scaffolding is selectively reused
from SwitchTrade's old stock finder fixture, not its launcher or orchestration.
No commercial ROM, BIOS, save or Nintendo header/logo is included. This is an
emulator fixture, not an image intended for physical hardware.

The program activates its emulated RFU peripheral, discovers a synthetic host,
joins and sends `[0x53544631, round]`. It must receive `[0x53544831, round]`,
then disconnects its RFU link and continues to round 2 in the same game memory.
A content reset/reload starts round 1 again and fails the host's round-2 check.
Peripheral activate/deactivate are game RFU operations, not emulator resets.

Rebuild with the pinned Arm GNU Windows toolchain and clean dependency checkout:

```powershell
python tools/gpsp_qualification/build_fixture.py --toolchain <toolchain-root> --dependency <gba-link-connection> --output <new-build-directory>
python tools/gpsp_qualification/p0_attach.py --root <stock-RetroArch-Win64> --fixture tests/fixtures/rfu/gpsp-attach/attach.gba --output <new-evidence-directory>
```

The harness copies the stock executable/core/runtime DLLs into a fresh directory,
creates a private config and a non-displayed Windows desktop, starts the test
game, then uses public menu key events to connect/disconnect/reconnect. It never
switches the user's displayed desktop or controls a user's RetroArch. It creates
no UDP command server. Menu control, test process startup/exit, and config writes
are **harness only**, prohibited in the product attach-only endpoint.

Retain raw diagnostics locally: they contain paths and may include frontend
environment details. Do not commit screenshots or frontend logs. A P0 pass only
proves this stock attach/exchange/detach/reattach flow; it does not qualify the
new Core endpoint, full integration, soak or physical interoperability.
