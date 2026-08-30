# Repository agent instructions

Before any implementation, test, build, installation, deployment, recovery, cleanup, deletion, or
operator handoff, read `docs/MISTAKES_TO_AVOID.md` completely and apply every relevant prevention
rule. Also read the task-specific ABC+D and TODO documents it references.

If a new failure, false assumption, unsafe instruction, or avoidable operator trip occurs:

1. stop advancing the run and preserve its first failure and recovery state;
2. perform only the committed, identity-bound recovery path;
3. prove cleanup and residue state;
4. add the incident, cause certainty, and prevention gate to `docs/MISTAKES_TO_AVOID.md` before any
   retry or handoff.

Never bypass source-clean, pairing, hardware, cleanup, release-identity, privacy, or physical
qualification gates to make progress appear successful. Never treat an intermediate gate, silence,
or successful cleanup as an overall functional pass.
