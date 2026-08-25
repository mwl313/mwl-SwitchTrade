# Current product-demo TODO — 2026-08-25

> Status: authoritative current execution order.
> Product scope: real Switch-to-real Switch. The PC-host implementation remains a protocol oracle
> and regression harness, not the production peer.
> Hardware policy: RTL8192EU is the beta-certified target. The runtime remains profile-driven so new
> hardware and drivers can be added without changing the RFU tunnel, GUI, or session logic.

## Immediate tasks — do in this order

1. **Freeze the production-beta repository baseline.**
   - Use `production-beta` as the sole integration branch.
   - Pin dependencies and record application, kernel, driver, firmware, and USB hardware versions.
   - Keep generated captures and runtime logs outside Git.

2. **Lock the beta hardware policy without hardcoding the product to one chipset.**
   - RTL8192EU (`0bda:818b`) is the certified default candidate.
   - RTL8188EU (`0bda:8179`) remains experimental and must not be selected automatically.
   - Use one modular hardware-profile registry for the CLI, launcher, health gate, and GUI.
   - A new USB ID or driver must be addable through a profile plus capability qualification, without
     modifying the RFU tunnel or frontend.
   - Keep certified, candidate, experimental, quarantined, and unsupported states distinct.

3. **Finish the fail-closed Windows/WSL hardware launcher.**
   - Detect USB ownership, `usbipd`, WSL/kernel state, driver binding, NetworkManager interference,
     stale interfaces/processes, required kernel modules, and runtime prerequisites.
   - Automatically perform safe recovery or give an exact corrective instruction.
   - Never begin a session using an unhealthy or uncertified adapter.

4. **Complete the universal health gate and recovery system.**
   - Validate USB -> driver -> interface -> real RF reception -> LDN decoding -> role capability ->
     association/control port -> encrypted transport readiness.
   - Discover across all permitted 2.4 GHz channels; channels 1/6/11 are only a quick health sample.
   - Detect a likely 5 GHz room and ask the user to recreate it on 2.4 GHz.
   - Add bounded watchdog, cleanup, retry, safe shutdown, and post-run adapter recovery.

5. **Complete production-grade logging.**
   - Create a unique run ID and directory for every attempt.
   - Record hardware, software, driver, channel, state transitions, counters, errors, recovery actions,
     and timing in JSONL plus readable console output.
   - Redact secrets, rotate logs, and produce a one-action diagnostic support bundle with a privacy
     manifest.

6. **Certify both RTL8192EU adapters.**
   - Test the current adapter and the additional matching adapter.
   - Cover cold attach, WSL/Windows restart, detach/reattach, recovery, RX/TX soak, teardown, discovery,
     host, guest, relay, repeated rooms, full trade, exit, and immediate reuse.
   - Classify intermittent Pia decryption failures and joined-session teardown delays.

7. **Implement the feature-neutral RFU tunnel.**
   - Terminate LDN, Pia, and Reliable locally at each endpoint.
   - Carry versioned RFU envelopes with session, direction, sequence, timing, player mapping, reconnect
     epoch, and original bytes for diagnosis.
   - Add deterministic two-player mapping, bounded queues, backpressure, stale-frame rejection,
     counters, and recovery behavior.

8. **Validate the tunnel without Switch hardware.**
   - Use unit tests, recorded-data replay, and two local endpoint simulation.
   - Inject drops, delays, duplicates, reordering, disconnects, and reconnects.

9. **Build the early GUI control backend.**
   - Expose a small local JSON API for readiness, hardware configuration, group operations, sessions,
     logging, recovery, and shutdown.
   - Keep radio and protocol behavior in WSL rather than the browser layer.

10. **Build the HTML/CSS first-demo interface.**
    - Main: `Host a Trade Group`, `Join a Trade Group`, and `Configuration`.
    - Host: group name, public/private choice, create action, then Trade Group Lobby.
    - Join: browse public groups or enter a passcode, then Trade Group Lobby.
    - Configuration: detected adapter, driver/capability/readiness state, safe adapter selection,
      repair/recheck, and diagnostics.
    - Lobby: group/code, endpoint readiness, Switch instructions, connection progress, leave/cancel,
      and diagnostic run ID.
    - Public-group browsing may use explicit mock/demo data until the real public service exists.

11. **Integrate the GUI with the real launcher, health gate, logs, and RFU tunnel.**
    - Show real state, block unsafe actions, surface actionable recovery, and stop cleanly.

12. **Run the first production Switch-to-Switch test.**
    - Use two RTL8192EU endpoints.
    - Complete room entry, movement, chair interaction, trade, save, menu return, and graceful exit.
    - Confirm that production does not depend on the PC-to-Switch emulator path.

13. **Run reliability and network-failure testing.**
    - Repeat trades and reconnects on LAN and WAN.
    - Exercise loss, delay, endpoint/tunnel restart, disconnect, stale-session rejection, and recovery.

14. **Package the private demo/beta.**
    - Ship a signed Windows bootstrap installer that detects/installs WSL, the isolated SwitchTrade
      distro/runtime, the versioned custom kernel artifact, USB/IP, the desktop app, and frontend.
    - Resume safely after the one Windows reboot that may be required for initial WSL enablement;
      otherwise use bounded `wsl --shutdown`, not a WSL reset or deletion.
    - Provide clean-machine installation, first-run hardware setup, repair, uninstall, rollback, user
      guidance, supported-version documentation, and diagnostic export.
    - Release privately before public rooms or additional activities.

## Backlog tasks — do in this order

1. **Repair and certify RTL8188EU support.**
   - Resolve receive death, Nintendo custom control-port association, AP+monitor deadlocks, and recovery,
     or retain a clearly limited support status if the hardware/driver cannot pass qualification.

2. **Add more supported chipsets and drivers.**
   - Qualify the suitable candidates already documented by the reference repositories.
   - Add each through the modular profile, capability, kernel-module, and health-gate workflow.
   - Add a verified dual-band USB option.

3. **Implement the real public-group service.**
   - Add public listing and matchmaking, authentication, privacy, expiration, abuse/rate controls, and
     regional relay selection. Public demo UI is not evidence that this production service exists.

4. **Polish the HTML/CSS interface.**
   - Add responsive refinement, visual identity, animation where useful, complete localization, and
     accessibility QA.

5. **Add trade decoding and history to the GUI.**
   - Integrate the completed payload decoder and show exchanged Pokémon with explicit privacy controls.

6. **Measure and improve movement latency.**
   - Compare native and tunneled cadence before tuning batching, pacing, queues, or transport behavior.

7. **Expand two-player Switch-to-Switch activities.**
   - Add Union Room presence/movement, Union Room trading, single battle, double battle, chat, and then
     other two-player RFU activities.

8. **Add larger multiplayer modes.**
   - Treat three/four-player modes and multiplayer minigames as separate milestones.

9. **Harden server operations.**
   - Add monitoring, scaling, backups, geographic relays, operational dashboards, and incident response.

10. **Complete public-release engineering.**
    - Add signed application/kernel releases and updates, reproducible builds, rollback, optional crash
      reporting, compatibility migrations, and long-term support policy.

## First product-demo screenflow

```text
Main -> Host a Trade Group -> Trade Group Lobby
Main -> Join a Trade Group -> Browse Public Groups -> Trade Group Lobby
                           -> Enter Group with Passcode -> Trade Group Lobby
Main -> Configuration
```

The real first milestone is a private/passcode Switch-to-Switch group. Public-group screens may be
demonstrated with clearly labeled mock/local data; the production directory and matchmaking service
remain backlog work.

## Implementation snapshot — beta.0 internal build

As of the `0.2.0-beta.0` internal build:

- Tasks 1-5 have working foundations: one integration branch, profile-driven hardware policy,
  Windows/WSL preflight, health-gated endpoint launch, structured run logs, and support bundles.
- Tasks 7-11 are implemented for internal validation: the feature-neutral RFU tunnel, relay-backed
  private sessions, real control API, static desktop frontend, and launcher/state integration.
- The tunnel mirrors the leader Switch's original LDN application advertisement and carries opaque
  Reliable AppData. It does not depend on trade opcodes, the Pokémon decoder, or a specific future
  two-player activity.
- Task 14 has a checksummed minimal-rootfs package/bootstrap foundation. Its isolated install, repair,
  rollback retention, and uninstall/purge path passed a throwaway-distro test. It provisions only the
  named `SwitchTrade` distro and deliberately leaves the global/custom WSL kernel policy unchanged.
- Task 6 still needs the second RTL8192EU and hardware qualification. Tasks 12-13 still need the
  requested real two-endpoint Switch test and reliability campaign. The final signed clean-machine
  installer still needs signing, reboot/resume validation, a genuinely clean external-machine test,
  and release approval.

Internal software validation is recorded in `docs/53-beta0-internal-build-20260825.md`. This snapshot
does not promote RTL8188EU or claim real Switch-to-Switch certification.
