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
recovery screen and can enter an explicitly labeled interface preview. The installed copy finds
`installer/Launch-SwitchTrade.ps1` beside it, starts the isolated WSL runtime without opening a
browser, and talks to the local JSON API at `http://127.0.0.1:8787`.

The current presentation implements the approved Linkline redesign foundation and honest UI-only
flows: Home, create/private join, an interactive Public Rooms Preview, Settings, and the persistent
Trade Room. Public rooms and party data are always labeled `Demo Preview`; the app does not invent a
remote trainer, shared readiness, or live party data while the authoritative services are unfinished.

The preliminary handoff is `docs/56-native-ui-ux-redesign-handoff-20260825.md`. The frozen backend and
privacy contracts are `docs/58` through `docs/61`; use
`docs/62-final-ui-overhaul-gpt-handoff-20260825.md` for the final GPT/owner UI review.

Radio and protocol logic does not live in this project. Hardware profiles, drivers, RFU behavior,
and future game features remain replaceable behind the existing control API.
