# SwitchTrade documentation

This directory contains the maintained public documentation for SwitchTrade. Dated experiment
notes, packet captures, agent handoffs, design exports, and retired prototypes are intentionally not
part of the public repository or release package.

## Maintained documents

- [Mistakes to Avoid](MISTAKES_TO_AVOID.md) — mandatory source of truth for observed failures,
  disproven assumptions, agent/operator mistakes, and recurrence-prevention gates. Read it before
  any implementation, test, release, deployment, recovery, or cleanup work.
- [Technical Guide](TECHNICAL_GUIDE.md) — architecture, repository map, runtime lifecycle, APIs,
  hardware policy, diagnostics, development workflow, and extension boundaries.
- [FireRed/LeafGreen Communication Protocol](FRLG_PROTOCOL.md) — the detailed, evidence-labelled
  protocol specification recovered by the project.
- [Development History](DEVELOPMENT_HISTORY.md) — milestones, corrections, and engineering lessons.
- [A/B/C Connection Architecture](80-abc-connection-architecture-20260829.md) — ordered readiness
  gates and the normative source of truth for the Switch-room side, mirrored-AP side, relay bridge,
  and verified cleanup.
- [ABC+D Orchestration Rewrite Plan](81-abcd-orchestration-rewrite-plan-20260829.md) — phased,
  exit-gated implementation plan for replacing orchestration while admitting only proven low-level
  components.
- [ABC+D Milestone 0 Baseline](82-abcd-milestone-0-baseline-20260829.md) — reproducible baseline,
  reuse-admission ledger, explicit replacement boundary, and known retained failures.
- [ABC+D Milestone 1 Coordinator](83-abcd-milestone-1-coordinator-20260829.md) — serialized run state,
  identity-bound launch ownership, restart recovery, cleanup guard, tests, and deliberate limits.
- [ABC+D Milestone 7 Distributed D Checkpoint](90-abcd-milestone-7-authority-d-checkpoint-20260830.md)
  — v2-only outcome preservation, ordered endpoint shutdown, measured local D5, launch-bound
  two-side barrier, D7-D11 local release, and the explicit remaining fault-qualification boundary.
- [ABC+D Milestone 7 Physical Harness](91-abcd-milestone-7-physical-harness-20260830.md) — the
  GUI-independent two-PC/two-Switch runner and its installed qualification boundary.
- [Single-PC dual-adapter Switchless C+D suite](93-single-pc-dual-adapter-switchless-cd-suite-20260831.md)
  — closed 10/10 qualification campaign for the remaining non-physical C+D and exact-resource
  boundaries; not a production dual-radio feature.
- [ABC+D Production Wrapper and Beta Cutover](94-production-wrapper-beta-cutover-20260831.md) — the
  current M8-M10 execution decision: deterministic one-radio wrapper, minimal GUI, Desktop support
  export, immutable package, and final two-PC/two-Switch acceptance.
- [Future TODO](FUTURE_TODO.md) — definitive implementation and qualification ledger for that
  architecture.
- [Core simplification planning bundle](core-simplification/README.md) — staged A/B/C planning
  documents for reducing the core architecture before implementation work begins.
- [Development hot-deploy](../scripts/dev/README.md) — source-only sync, run, test, doctor, and
  overlay cleanup without changing the installed production runtime.
- [Known Issues](KNOWN_ISSUES.md) — authoritative beta defect register, evidence, workarounds, and
  acceptance checks.

The root [README](../README.md) is the short installation and user guide. Relay operators should also
read [relay/DEPLOYMENT.md](../relay/DEPLOYMENT.md), and distribution engineers should read
[installer/README.md](../installer/README.md).

## Documentation rules

1. Read `MISTAKES_TO_AVOID.md` before beginning work, apply its relevant prevention rules, and update
   it before retrying after a new failure or avoidable operational mistake.
2. Update these documents in the same commit as a behavior, contract, or packaging change.
3. For the production connection rework, the A/B/C+D architecture and definitive TODO are
   normative. Source code and tests show current implementation status; a disagreement is an open
   implementation gap, not permission to weaken a required gate.
4. Label protocol claims as observed, source-confirmed, implemented, or inferred.
5. Never commit credentials, tokens, private keys, raw support bundles, packet captures, or player
   data.
6. Put incomplete product work in `FUTURE_TODO.md`; do not describe it as a beta capability.
