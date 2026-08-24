# Unattended beta foundations — 2026-08-25

## Built without Switches or the second RTL8192EU

- Saved the current ordered immediate/backlog roadmap and first-demo screenflow in
  `docs/50-current-product-demo-todo-20260825.md`.
- Changed the shared radio profile schema to include explicit `auto_select` policy. RTL8192EU is the
  only automatic beta candidate; RTL8188EU is `quarantined`, observation-only, and never automatic.
- Updated the Linux selector to consume that policy and the Windows preflight to select an actually
  attached eligible device instead of requiring every profiled chipset. Windows can disambiguate
  duplicate USB IDs with `-BusId`.
- Added a shared Python hardware-profile reader for the frontend/control layer.
- Added per-run JSONL/readable diagnostics, secret-field redaction, run IDs, guarded run rotation,
  and privacy-manifest support bundles.
- Added a versioned feature-neutral RFU envelope, reconnect epoch/sequence rejection, bounded
  backpressure queue, and deterministic two-player host/guest mapping. Integration at the real RFU
  boundary remains open.
- Added a local FastAPI control surface for status, shared hardware profiles, local-demo group
  creation/join, session stop, and support-bundle export.
- Implemented the main/host/join/public/passcode/configuration/lobby demo screens using the exact
  approved Emerald Canvas primitives and bitmap glyph data from `SwitchTrade-UI-Kit.zip`.
- Added a release-manifest generator and a Windows bootstrap-installer design covering WSL,
  USB/IP, custom-kernel consumption, reboot resume, coexistence, repair, uninstall, and rollback.

## Checks completed without hardware

- Python product/payload tests: 20 passed.
- New Python sources compile.
- PowerShell preflight parses without errors.
- WSL radio shell scripts pass `bash -n`.
- UI TypeScript type-check passes.
- UI ESLint passes.

## Explicitly not claimed

- The UI package could not run/build in this workspace because its approved package manager blocked
  dependency build scripts. The restriction was not bypassed.
- The frontend is not yet wired to the Python control API or radio/tunnel runtime.
- The RFU envelope is not yet connected to the decoded Reliable/RFU boundary.
- Windows/WSL mutation, USB ownership, actual RX, Switch discovery, two-card operation, LAN/WAN,
  installer reboot/resume, and product acceptance were not run.
- RTL8192EU remains the beta candidate until the second-card Switch-to-Switch gate passes.
