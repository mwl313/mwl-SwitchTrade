# Archive

This directory contains evidence and historical development inputs, not production runtime code.

- `agent-history/`: previous agent planning artifacts.
- `legacy/`: VM-era scripts, backups, and preserved key material.
- `pokemon/fixtures/`: Pokémon files used to ground payload analysis and regression work.
- `pokemon/received-*`: preserved physical-trade results.
- `references/`: ignored nested upstream/reference repositories and the obsolete emulator junction.

Production code is in `switchtrade/`, `bridge/`, and `relay/`. Do not import runtime modules from
`archive/` or include this directory in release packages.
