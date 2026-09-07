# Switch-to-Switch software qualification and final evidence

## Source and scope

Branch: `Simple-Architecture`, repository `mwl313/mwl-SwitchTrade`.
The initial clean remote handoff was `207537e28a66207fd7aad970e34b6487dfef1608`.
The attached specification is preserved as
`SWITCH_TO_SWITCH_FINAL_MASTER_PROMPT_20260907.md`. Only software and local
virtual-boundary tests were performed. Main, tags, releases, deployment, physical
radios, user WSL provisioning/reset and emulator implementation are untouched.

## Completion record, without a self-referential SHA

`ABC_SOFTWARE_PREFLIGHT_CLOSURE.json` is the tracked **acceptance manifest**:
all I01-I18 and T01-T44 map to actual current source and tests. Its pending labels
are intentional, not a stale checklist or a claim that CI has already passed.
A Git file cannot contain the SHA of its own commit without changing that SHA.

The dependent `software-preflight` CI job runs only after **both Windows and
Ubuntu mandatory jobs succeed**, including every required full-test/build/check
step, on the same source commit. It publishes:

- artifact `abc-software-preflight-<exact SHA>`;
- file `ABC_SOFTWARE_PREFLIGHT_CLOSURE.final.json`;
- literal final SHA, CI run URL and platform conclusions;
- all 18 issue closures and all 44 acceptance results;
- COMPLETE / `ABC SOFTWARE PREFLIGHT: PASS`, explicitly software-only.

That generated JSON and its run are the final closure record. It does not create
another commit. Until the artifact exists and its exact SHA matches the branch,
the repository manifest alone must **not** be reported as PASS. A later source
change requires new full tests and new same-SHA CI evidence.

Read the final user report for the exact artifact/SHA, local full-test result and
both platform results. If resuming before that report exists, inspect the latest
CI for `git rev-parse HEAD`; diagnose any failure, preserve first cause, and
rerun final qualification after any fix. No functional software gap is knowingly
deferred to physical testing.

## Current verified software path

Actual CLI, default Switch driver, Direct A/B, StageSession, installed LDN 0.0.17,
LdnDataPlane, TunnelSim/Pia/Reliable/CoreTunnelAdapter, CoreSupervisor, WireClient
and real localhost Core relay/WebSockets transport opaque RFU in both directions.
Two automatic Generations reuse one Pair. Tests cover native local room end,
late users (including an actual 181-second mirror wait), active reconnect,
pre-active loss, cancellation, strict resource cleanup, first/secondary failures,
key/dependency/identity admission and import isolation. The original PowerShell
dev entrypoint, console interrupt, Linux parent guardian and radio scripts are
qualified at their documented OS primitive seams, not replaced by fake Core.

See `SWITCH_TO_SWITCH_SOFTWARE_EVIDENCE.md` for the exact REAL/substituted map,
packet test observations and CI failure diagnoses. Historical counts are not
substitutes for the final source run. The final local full run uses a fresh
workspace-owned `.qualification/pytest-<unique>/authority.sqlite3` via
`SWITCHTRADE_AUTH_DB`, never the user's installed authority DB.

## Next physical step, only after software closure

Use `SWITCH_TO_SWITCH_PHYSICAL_RUNBOOK.md` for the common trusted TLS relay,
exact Host/Guest commands, pre-existing runtime/key/USB prerequisites, native
game actions, first and second Generation success criteria, privacy-safe logs,
Ctrl+C and ownership-bound residue checks. Physical Switch/game/radio behavior
has **not** been executed or certified. Do not bypass a gate or use a cleanup
success as evidence of functional game communication.

Future emulator work implements the generic endpoint contract; Core/Relay retain
opaque protocol-tagged payloads and generic Pair/Generation ownership. No emulator
or legacy Room/Ready/Continue/checkpoint path was added to this execution flow.
