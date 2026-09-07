# Switch-to-Switch final software preflight — current checkpoint

Task remains IN_PROGRESS / FAIL, not a handoff or completion claim.

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
