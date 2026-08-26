# SwitchTrade Future TODO

This list contains work deliberately excluded from `0.2.0-beta.1`. Items are ordered within each
section. None should be presented as a current beta capability.

## 1. Post-release qualification

1. Run the complete production topology with two Windows PCs, two RTL8192EU adapters, two Switch
   consoles, and the hosted relay across two independent NATs.
2. Repeat full create/join, room entry, movement, trade, save, menu return, graceful exit, second
   attempt, reconnect, and room reuse cycles.
3. Run long-duration radio and relay soak tests with loss, reorder, latency, endpoint restart, relay
   restart, and temporary internet loss.
4. Qualify a second physical RTL8192EU unit and record hardware revision, USB topology, driver, signal,
   channel, and receive-health results.
5. Validate Install, Update, Repair, Rollback, Uninstall, reboot continuation, and custom-kernel restore
   on clean supported Windows machines, including non-ASCII usernames and managed-policy failures.
6. Test recovery from relay database backup and verify active-room expiration after an intentional
   authority reset.
7. Add Windows code signing and trusted timestamping before a wider public release. The private beta
   remains intentionally unsigned.

## 2. Reliability and product operations

1. Add an update channel and verified in-app update flow with rollback.
2. Add crash reporting that preserves the existing redaction and opt-in boundaries.
3. Add relay dashboards/alerts, backup automation, capacity limits, and an operator runbook.
4. Design shared live-peer routing, distributed presence, ordered events, and rate limits before using
   multiple relay workers or replicas.
5. Improve reconnect UX for endpoint restart, adapter reattachment, and expired room attempts.
6. Continue movement/jitter optimization using timestamped VBlank, queue-depth, RTT, retransmission,
   and user-visible motion measurements.
7. Perform a complete accessibility pass: keyboard-only, screen reader, high contrast, 200% scaling,
   localization length, and reduced motion.
8. Continue owner-led visual polish without changing server authority or protocol contracts.

## 3. Additional Switch-to-Switch features

1. FireRed/LeafGreen link battles.
2. Union Room flows.
3. Other Direct Connection multiplayer modes exposed by the Switch application.
4. Feature-neutral session negotiation so both endpoints select the same protocol module before radio
   roles lock.
5. Native captures and replay fixtures for every added feature's opening, blocks, commands, barriers,
   cancellation, and teardown.

All product features remain Switch-to-Switch. PC-to-Switch trading is a development harness, not a
future product mode.

## 4. Hardware and driver expansion

1. Diagnose and fix RTL8188EU control-port association, AP+monitor concurrency, and receive-death
   behavior under WSL; keep it quarantined until it passes the same gates as RTL8192EU.
2. Physically qualify the already-profiled MT7610U, MT7612U, RT2770, RT3070, RT3572, and RTL8821CU
   candidates through observe → join → host → full trade → soak.
3. Re-evaluate AR9271 only after the known association failures have a reproducible driver-level fix.
4. Add other upstream-supported adapters through the data-driven matrix and diagnostic promotion
   process.
5. Add 5 GHz-capable hardware and validate LDN channels 36, 40, 44, and 48.
6. Automate firmware inventory and package validation for newly supported adapters.
7. Build a new custom kernel only when a required driver/configuration is absent; do not fork the core
   application for a chipset.

## 5. Party display, history, and optional statistics

1. Complete live two-party 2×3 presentation with validated hover/focus stat details during a native
   Switch-to-Switch session.
2. Expand the decoder fixture corpus across languages, versions, party conditions, mail, ribbons, and
   malformed records.
3. Add a local trade history backed only by fail-closed committed-trade evidence.
4. If separately approved, design an optional server ingestion service for committed trades with
   explicit consent, data minimization, retention, deletion/export, coarse location, and
   pseudonymization. This service must remain separate from the opaque RFU relay.
5. Never upload raw RFU frames or complete Pokémon records merely to produce statistics.

## 6. Developer experience

1. Add deterministic protocol traces generated from synthetic/replay data so contributors do not need
   private captures.
2. Add API schema generation for the local and relay v1 contracts.
3. Add reproducible clean-machine CI for WPF publish, installer audit, package inventory, relay smoke,
   and kernel manifest validation.
4. Publish hardware qualification templates and a driver contribution guide.
5. Keep `TECHNICAL_GUIDE.md`, `FRLG_PROTOCOL.md`, and this file updated with every behavior change.
