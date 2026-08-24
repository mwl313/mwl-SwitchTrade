# SwitchTrade UI

Local desktop frontend for the first SwitchTrade product demo.

- Screen flow: `docs/50-current-product-demo-todo-20260825.md`
- Product-state reference: `docs/18-user-flow.md`, subject to the current production corrections
- Visual system and exact reusable assets: `ui/SwitchTrade-UI-Kit/`
- Primary renderer: one 240x160 Canvas scaled by integer factors only

The current source implements main, host, join, public-list, passcode, configuration, and lobby
screens. Public groups are explicit demo data until the production matchmaking service exists. The
Python control API lives in `switchtrade/control.py`; live API/radio/tunnel wiring is not yet claimed.

The generated Sites/Vinext dependency set is pinned in `pnpm-lock.yaml`. If the workspace blocks
dependency build scripts, do not bypass its supply-chain policy; build in the approved release
environment instead.
