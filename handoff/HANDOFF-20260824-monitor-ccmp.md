# Handoff — PC-host rtl8xxxu monitor/TAP fix (2026-08-24)

## Read first

`docs/31-pc-host-monitor-ccmp-20260824.md` is authoritative. Raw pcaps are local under
`logs/golden/pc_host_bridge_diag_20260824_141144/` and must remain uncommitted.

## Current branch state

- Main repository: `golden-capture-re`.
- Emulator repository (`emu/`): `gptsolreview`, fix commit `a740440`.
- The native Net/Session fix from `be18d57` remains correct but was not reached in the first
  PC-host smoke test.

## Root cause and fix

RTL8192EU received all Switch traffic. Its `rtl8xxxu` monitor vif supplied protected frames
with CCMP header/MIC retained but SNAP payload already decrypted. Kinnay attempted a second
AES-CCM decrypt and silently dropped the frames, so no Switch ARP reached `ldn-tap`.

`frlgsim.transport.install_monitor_ccmp_compat()` now normalizes this exact retained-wrapper
form at runtime before `ldn.create_network()`. Site-packages is not modified. Two focused
tests and replay of the real failing pcap pass; all seven captured ARPs become TAP-deliverable.

## Live gate result — PASS

`logs/golden/pc_host_ccmp_fix_live_20260824_144343/` crossed every boundary: ARP request and
PC reply, Net `0x12`, Session `0 -> 2/5 -> 6`, and the first guest Reliable INIT. All 119 Pia
datagrams decrypted with zero failures. Hashes and counts are in the authoritative doc.

The UI still reported unavailable because the host/parent Reliable path is deliberately gated.
The Switch sent FireRed INIT metadata at `fff0`, then 77 sequential `WC` requests while its
window base remained `fff0`; the PC sent no bulk ACK or `WA` accept.

## Immediate implementation

Implement the native host/parent Reliable bootstrap using the CH1 two-Switch gold:

1. bulk-ACK guest `fff0` with next-expected `fff1`;
2. accept the first guest `WC` request;
3. send host INIT `WA` and cumulative ACK;
4. continue parent RFU/NI direction, keeping game release gated until the child is seated.

Also repair HostTransport graceful teardown: after the peer left, context exit exceeded the
15-second radio-thread grace and required the selector to remove the stale AP. Both cards passed
post-cleanup RX health, so this is a shutdown lifecycle bug rather than receive death.

## Safety constraints

- Run `scripts/wsl-radio-prepare.sh` / `radio-health-gate.sh` before each radio workflow.
- RTL8192EU remains host; RTL8188EU remains observer/guest/relay, not AP+monitor host.
- Do not commit raw pcaps, `prod.keys`, derived keys, or console secrets.
- Do not release the game engine after Pia finalize until a separate host/parent Reliable/RFU
  path is implemented from the native gold.
