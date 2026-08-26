# SwitchTrade native Windows client

This is the primary product-demo client. It is a native WPF application and does not use Electron,
Chromium, WebView2, or an external browser.

The maintained screen flow, feature inventory, and layer terminology are documented in
`docs/54-native-ui-flow-and-runtime-structure-20260825.md`.

Build a self-contained x64 executable from Windows PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\apps\desktop\Publish.ps1
```

The output is a single `artifacts/native/SwitchTrade/SwitchTrade.exe`. A standalone copy opens a
factual recovery screen when its installed runtime is absent. The installed copy finds
`installer/Launch-SwitchTrade.ps1` beside it, starts the isolated WSL runtime without opening a
browser, and talks to the local JSON API at `http://127.0.0.1:8787`.

The current presentation implements Visual Overhaul 3: a native dark token system, embedded
Space Grotesk/Inter/Space Mono fonts, split adaptive views, explicit high-contrast ComboBox states,
Windows High Contrast and reduced-motion handling, real server-authoritative private/public rooms,
typed checksum-valid party presentation, and coordinator-owned persistent Trade Room state. Public
room navigation is capability-gated by the deployed relay; the app never substitutes sample rooms,
trainers, readiness, or party data. The client intentionally has no Privacy tab, consent prompt, or
analytics switch.

The current source of truth is `docs/54-native-ui-flow-and-runtime-structure-20260825.md`. The dark
handoff is `docs/73-stitch-dark-ui-codex-integration-handoff-20260826.md` and its implementation
report is `docs/74-stitch-dark-ui-overhaul-3-implementation-report-20260826.md`. Frozen backend
contracts are in `docs/58` and `docs/59`; public directory behavior is versioned as
`public-directory.v1`.

Radio and protocol logic does not live in this project. Hardware profiles, drivers, RFU behavior,
and future game features remain replaceable behind the existing control API.
