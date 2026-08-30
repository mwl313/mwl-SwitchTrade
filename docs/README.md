# SwitchTrade documentation

This directory contains the maintained public documentation for SwitchTrade. Dated experiment
notes, packet captures, agent handoffs, design exports, and retired prototypes are intentionally not
part of the public repository or release package.

## Maintained documents

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
- [M7 two-PC distributed handoff](HANDOFF-M7-TWO-PC-DISTRIBUTED-20260830.md) and
  [PC B preflight handoff](HANDOFF-PC-B-M7-TWO-SWITCH-PREFLIGHT-20260830.md) — coordinated physical
  execution and evidence rules.
- [Future TODO](FUTURE_TODO.md) — definitive implementation and qualification ledger for that
  architecture.
- [Known Issues](KNOWN_ISSUES.md) — authoritative beta defect register, evidence, workarounds, and
  acceptance checks.

The root [README](../README.md) is the short installation and user guide. Relay operators should also
read [relay/DEPLOYMENT.md](../relay/DEPLOYMENT.md), and distribution engineers should read
[installer/README.md](../installer/README.md).

## Documentation rules

1. Update these documents in the same commit as a behavior, contract, or packaging change.
2. For the production connection rework, the A/B/C+D architecture and definitive TODO are
   normative. Source code and tests show current implementation status; a disagreement is an open
   implementation gap, not permission to weaken a required gate.
3. Label protocol claims as observed, source-confirmed, implemented, or inferred.
4. Never commit credentials, tokens, private keys, raw support bundles, packet captures, or player
   data.
5. Put incomplete product work in `FUTURE_TODO.md`; do not describe it as a beta capability.
