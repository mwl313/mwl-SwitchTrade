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

## Immediate live gate

Run one health-gated RTL8192EU host plus RTL8188EU observer capture. Ask the user to select
`CODEX` once. Preserve monitor, TAP, Pia JSONL, and observer evidence until these milestones
are classified:

1. Switch ARP reaches TAP and PC ARP reply appears over RF.
2. Switch sends Net `0x12` and Session `0`.
3. PC sends Session `2` and `5`.
4. Switch sends Session `6` and first Reliable INIT.

The patched room started after diagnosis received no manual join attempt and is inconclusive.
Do not report live success until a new attempt crosses these milestones.

## Safety constraints

- Run `scripts/wsl-radio-prepare.sh` / `radio-health-gate.sh` before each radio workflow.
- RTL8192EU remains host; RTL8188EU remains observer/guest/relay, not AP+monitor host.
- Do not commit raw pcaps, `prod.keys`, derived keys, or console secrets.
- Do not release the game engine after Pia finalize until a separate host/parent Reliable/RFU
  path is implemented from the native gold.
