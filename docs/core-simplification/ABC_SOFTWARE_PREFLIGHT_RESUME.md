# Switch-to-Switch final software preflight — current checkpoint

Task remains IN_PROGRESS / FAIL, not a handoff or completion claim.

## Latest checkpoint (2026-09-07; supersedes progress bullets below)

- Five packets pushed on Simple-Architecture through
  `74a0c326b28801c4316852cf2dd90266fec26c4a`; CI #113 success on both platforms.
- Actual CLI/relay/LDN/DirectA+B/StageSession/TunnelSim/Pia/Reliable qualification
  exchanges opaque RFU both ways over two automatically repeated generations.
- Real 181-second mirror human wait followed by physical-boundary join passes.
- Current uncommitted packet: pure cancellation groups with independently proven
  resource release; actual Direct fault tests; Linux gate-to-CLI parent guardian;
  real WebSocket interruption scenarios. No physical WSL/device operation.
- Remaining: close actual interruption tests; audit input/dependency failures and
  diagnostic evidence; runbook; complete all I01–I18/T01–T44; full pytest and CI for
  the same final SHA. Current closure JSON is intentionally not a PASS.
- Full local pytest must set SWITCHTRADE_AUTH_DB to a fresh workspace-owned
  `.qualification/pytest-<unique>/authority.sqlite3`, never the user's runtime DB.

## Initial checkpoint (historical progress, not current status)

- Specification: `SWITCH_TO_SWITCH_FINAL_MASTER_PROMPT_20260907.md` (saved from the attachment).
- Branch: `Simple-Architecture`; remote handoff `207537e28a66207fd7aad970e34b6487dfef1608` was fetched and matched the clean local checkout.
- Completed/pushed packet: `f2ca6b75ccd3b9f7588b7feedf7df458900989f7`, early resource ownership, bounded cancellation, dependency classification, socket cleanup.
- Evidence for that packet: 88 focused tests, exit 0; actual A/B and StageSession owners with test hardware boundaries. This is not final RFU qualification.
- Current packet: endpoint-neutral local end, same-Pair repeat, pending offer close, pre-active cancellation/loss, and epoch-change awareness. Focused integration checks pass, but real TunnelSim/CLI qualification remains outstanding.
- Preserve all I01–I18 and T01–T44. Prior PASS cells were reset to NOT_RUN for final-source qualification; earlier partial observations remain labeled historical.
- Remaining: real-protocol/CLI/relay two-generation qualification; exact wait/lease policy; actual PowerShell/WSL-entry boundary tests; CI104 file-access diagnosis; runbook; full pytest and Windows/Ubuntu CI for one final SHA.
- No physical device or WSL installation/reset action has been performed. No main, tag, release, deployment, or emulator work is authorized here.
- Next source: `core/supervisor.py`, `transport/client.py`, `relay/pair_store.py`, `relay/core_server.py`, `core_cli.py`, then actual LDN/TunnelSim protocol qualification seams. Do not reload historical incident archives.

Correction to earlier notes: the claimed readiness-worker circular-wait cause was not established. Canceling the asyncio wrapper does not join its worker; explicit StageSession stop/readiness wake and bounded thread ownership are now tested.
