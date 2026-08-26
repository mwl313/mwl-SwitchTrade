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
- [Future TODO](FUTURE_TODO.md) — work deliberately excluded from the current beta.

The root [README](../README.md) is the short installation and user guide. Relay operators should also
read [relay/DEPLOYMENT.md](../relay/DEPLOYMENT.md), and distribution engineers should read
[installer/README.md](../installer/README.md).

## Documentation rules

1. Update these documents in the same commit as a behavior, contract, or packaging change.
2. Treat source code and tests as authoritative when a document and implementation disagree.
3. Label protocol claims as observed, source-confirmed, implemented, or inferred.
4. Never commit credentials, tokens, private keys, raw support bundles, packet captures, or player
   data.
5. Put incomplete product work in `FUTURE_TODO.md`; do not describe it as a beta capability.
