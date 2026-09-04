# Context map

Start with the nearest `AGENTS.md`, this map, and the task-specific normative documents. The
historical archive is not default context.

| Task shape | Read next | Incident lookup |
| --- | --- | --- |
| Repository code, tests, or documentation | `docs/MISTAKES_TO_AVOID.md`, relevant `80-abc-connection-architecture-20260829.md` and `FUTURE_TODO.md` sections | Only if a trigger applies |
| Desktop or local-service lifecycle | Relevant application/runtime source and tests | Search exact error, lifecycle, or recovery term |
| Relay, authority, or WebSocket | Relevant relay source and contract tests | Search exact relay code/path |
| WSL, USB, radio, or driver | Relevant radio/emulator guide and tests | Search exact component/failure code |
| Installer, update, repair, or release | Relevant installer guide and lifecycle tests | Search exact release/recovery path |
| Recovery or cleanup | Exact recovery owner and state contract | Always search the exact path/code first |

When an incident lookup is triggered, use `docs/incidents/INDEX.md` to locate matching entries and
open only the necessary archive ranges. Do not read the archive from start to finish.
