# Repository agent instructions

Before implementation, testing, building, installation, deployment, recovery, cleanup, deletion, or
handoff:

1. Confirm the exact branch, base commit, and worktree status.
2. Read the nearest applicable instructions and the task-specific normative ABC+D/TODO sections.
3. Work in one conceptual packet at a time and preserve unrelated changes.
4. Read only task-relevant context. Do not load the historical incident archive by default.
5. Search `docs/incidents/INDEX.md` only for an exact subsystem, stable error code, failure path,
   recovery path, cleanup operation, or explicitly requested historical analysis.
6. Keep source, runtime, process, device, release, and evidence identities explicit.

Global invariants are in [`docs/agent/INVARIANTS.md`](docs/agent/INVARIANTS.md); routing is in
[`docs/agent/CONTEXT_MAP.md`](docs/agent/CONTEXT_MAP.md). The legacy incident body is preserved at
[`docs/incidents/archive/MISTAKES_TO_AVOID-legacy-20260901.md`](docs/incidents/archive/MISTAKES_TO_AVOID-legacy-20260901.md)
and is historical evidence, not default context.

If a new failure or false assumption occurs, stop, preserve the first failure and recovery state,
use only the identity-bound recovery path, prove residue, and record the incident before retrying or
handing off. Never bypass source, identity, hardware, privacy, cleanup, or physical gates. Silence,
an intermediate gate, or successful cleanup is not an overall functional pass.
