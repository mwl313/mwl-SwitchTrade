# Production beta priorities — 2026-08-25

> Status: approved planning baseline. No implementation in this document has started.
> Product scope: real Switch-to-real Switch. The PC-host trade implementation remains a protocol
> oracle and regression harness, not the production peer.

## Current baseline

- The complete PC-host trade, save, menu return, and room-exit path has passed on real hardware.
- WSL2 with RTL8192EU (`0bda:818b`, in-kernel `rtl8xxxu`) has joined a real Switch and carried the
  complete FRLG stack through RFU/game traffic. It is the only production-beta hardware candidate.
- RTL8188EU (`0bda:8179`) is quarantined from the beta. Its patched vendor driver can receive and
  decode advertisements, but real guest association fails at Nintendo's custom nl80211 control-port
  protocol and AP+monitor can deadlock. It may be used only for observation/driver research.
- `config/wsl-radio-hardware.tsv` now marks RTL8192EU as the only auto-selectable beta candidate and
  quarantines RTL8188EU to observation. The same table remains the single policy source for the CLI,
  launcher, and future GUI so additional hardware stays profile-driven.
- A second RTL8192EU is expected on 2026-08-26. The first production test will use one identical
  8192EU at each local endpoint, removing the 8188 driver from the result.
- Application, protocol, relay, payload-decoder, documentation, and emulator histories are merged on
  `production-beta`. Runtime code is tracked under `bridge/` in this repository.
- The WSL kernel remains separate at `mwl313/wsl2-kernel-build`. Kernel source, binary artifacts, and
  out-of-tree modules must not be copied into this application repository.

## Immediate beta blockers, in order

### P0 — Repository and release control

1. Use `production-beta` as the only integration branch.
2. Require all application work to land in this repository; do not make new production commits in the
   old standalone emulator repository.
3. Keep old branches and repositories read-only until the consolidated branch passes tests; archive
   them afterward instead of deleting evidence.
4. Keep captures and generated runtime logs out of Git. Commit small manifests, hashes, fixtures, and
   conclusions only.
5. Pin dependency versions and record the application commit, kernel build, driver, firmware, and
   hardware USB ID in every release.

### P1 — Universal WSL reliability

1. Build one fail-closed launcher that owns the full Windows -> usbipd -> WSL -> driver -> application
   lifecycle and gives actionable recovery instructions without an LLM.
2. Detect and resolve VMware USB Arbitrator ownership, missing USB/IP attachment, wrong WSL distro,
   wrong kernel, missing `ccm`/`cmac`/`tun`, NetworkManager ownership, stale vifs, stale processes, and
   missing keys before starting a session.
3. Auto-select only production-certified hardware. An unknown, experimental, or quarantined device
   must never be silently used.
4. Layer health checks: USB ownership -> driver/netdev -> real RF receive -> LDN advertisement decode
   -> role capability -> association/control-port -> CCMP/Pia readiness.
5. Add bounded watchdog and teardown handling. A failed run must leave the card reusable or clearly
   request one safe recovery action.
6. Scan all permitted 2.4 GHz channels for discovery. Channels 1/6/11 remain a quick health sample,
   not a claim that FRLG only uses those channels.
7. Detect a likely 5 GHz room and tell the user to recreate it on 2.4 GHz; neither owned Realtek card
   supports 5 GHz.

### P2 — RTL8192EU production qualification

1. Repeat cold attach, WSL restart, Windows restart, suspend/resume, detach/reattach, and failed-run
   recovery tests without manual driver repair.
2. Use the two RTL8192EU cards for symmetric endpoint testing: discovery, host, guest, relay, repeated
   room entry, full trade, graceful exit, and immediate second session.
3. Reproduce and classify the intermittent Pia decrypt failures seen in the first controlled WSL join.
   No silent authentication failure may be accepted as normal without byte-level proof that it is an
   irrelevant duplicate/stale frame.
4. Resolve or bound the joined-session teardown thread timeout.
5. Run RX/TX soak, USB/IP reconnect soak, and repeated full-session soak with zero unrecovered radio
   deaths, zero kernel drops in the acceptance captures, and complete post-run diagnostics.
6. Publish the RTL8192EU as beta-supported only after the two-card real Switch-to-Switch gate passes.

### P3 — Extensive diagnostics and support logging

1. Create one run directory per attempt with a unique run ID and UTC/local timestamps.
2. Record application commit, kernel, module/firmware identity, USB ID, driver, interface/phy, channel,
   relay/session ID, arguments with secrets redacted, and all state transitions.
3. Capture structured JSONL events plus human-readable console output, counters, warnings, reconnects,
   queue drops, decrypt failures, watchdog events, and teardown results.
4. Preserve encrypted Pia/RFU wire bytes needed for offline diagnosis while never logging `prod.keys`,
   passphrases, access tokens, or raw secrets.
5. Add automatic log rotation/size limits and a one-click support bundle with a privacy manifest.
6. Make every fatal UI error show the run ID and an export-logs action.

### P4 — Feature-neutral RFU tunnel

1. Terminate LDN, Pia, and Reliable locally at both endpoints. Do not relay raw 802.11 ACK/SIFS timing
   over the WAN.
2. Define a versioned RFU envelope containing session, direction, RFU frame/slot, sequence, timestamp,
   player mapping, reconnect epoch, and the original bytes for audit.
3. Pass held keys, block requests/fragments, standby/close commands, and packet payloads without
   interpreting trade, movement, or battle meaning.
4. Add deterministic two-player owner/player remapping, bounded queues, backpressure, stale-frame
   rejection, reconnect epochs, and per-direction health counters.
5. Validate offline replay, two local endpoints, two real Switches on LAN, then controlled WAN
   latency/loss/reconnect conditions.

### P5 — Early GUI/control surface

1. The frontend is HTML and CSS, with minimal JavaScript only for interaction. Reuse the existing UI
   kit after its bundled font/license files are reviewed and preserved.
2. A small Python/Windows control backend may host the frontend (for example pywebview/WebView2) and
   expose a stable JSON API. Radio/protocol logic stays in WSL, not in the browser layer.
3. Beta screens are limited to first-run diagnosis, ready/error status, create room, join room, session
   progress, stop/recover, and export logs.
4. The GUI must consume the same hardware profile and readiness result as the CLI; it must not maintain
   a second compatibility list.
5. Accessibility, keyboard operation, clear Korean/English strings, and safe cancel/close behavior are
   beta requirements. Visual polish is not.

### P6 — Beta release gate

1. Complete a real Switch-to-Switch trade using the production RFU tunnel and two RTL8192EU cards.
2. Repeat full trade/exit/rejoin cycles and verify both games' final save state.
3. Pass LAN and WAN fault tests, installer/uninstaller recovery, clean-machine setup, log export, and
   rollback to the previous application/kernel bundle.
4. Document supported Windows/WSL/kernel/hardware versions and every known limitation.
5. Ship as a limited beta before adding public rooms, more activities, or more drivers.

## Future backlog after the beta gate

### Hardware and drivers

- Fix RTL8188EU properly: implement Nintendo custom control-port TX/RX support in the vendor driver or
  prove a safe userspace association alternative; resolve AP+monitor deadlocks; rerun the full matrix.
- Add the already-tested upstream [`tornadus/frlg-ldn-trade`](https://github.com/tornadus/frlg-ldn-trade)
  devices as candidates, not automatic claims:
  - ALFA AWUS036ACHM / MediaTek MT7610U / `mt76x0u` — upstream reliability: high.
  - Realtek RTL8821CE / `rtw88_8821ce` — upstream reliability: high, but PCIe/native Linux evidence does
    not establish WSL USB/IP support.
  - AMD RZ616 / `mt7921e` — upstream reliability: low; diagnostic candidate only.
- Keep Intel AX200/`iwlwifi` and Atheros AR9271/`ath9k_htc` blocked unless new evidence overturns the
  upstream IP-assignment failures.
- Add other chipsets through the existing profile/kernel-module workflow only after interface, receive,
  transmit, role, soak, and real-Switch gates pass.
- Add a verified dual-band USB option so 5 GHz rooms do not require recreation.

### Product features

- Graceful HTML/CSS UI development, responsive layout, visual polish, localization, and accessibility QA.
- Integrate the completed Pokémon payload decoder: privacy-controlled trade history and traded Pokémon
  display in the GUI.
- Revisit movement jitter only after the generic Switch-to-Switch tunnel is live; measure native versus
  tunneled cadence before changing code.
- Add Union Room presence/movement, Union Room trade, single battle, double battle, chat, then other
  two-player activities. Each activity gets one native boundary trace and replay/real-hardware tests,
  not a new PC-side gameplay emulator.
- Treat four-player multi battle and multiplayer minigames as separate milestones.
- Server work: authenticated matchmaking, private codes, abuse/rate controls, observability, geographic
  relay selection, operations, backups, and privacy policy. Public rooms remain post-beta.
- Signed application/kernel updates, rollback, crash reporting opt-in, support-bundle redaction, and
  reproducible release builds.

## Explicitly deferred

- Making RTL8188EU appear production-ready through retries or optimistic capability labels.
- Graceful visual UI polish before the control/logging API is stable.
- Raw 802.11 WAN relay as the production architecture.
- PC-controlled battle logic or decoding every player input type.
- Public server launch before a private two-user beta is reliable.
