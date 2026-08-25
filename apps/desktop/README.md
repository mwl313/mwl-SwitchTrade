# SwitchTrade native Windows client

This is the primary product-demo client. It is a native WPF application and does not use Electron,
Chromium, WebView2, or an external browser.

The maintained screen flow, feature inventory, and layer terminology are documented in
`docs/54-native-ui-flow-and-runtime-structure-20260825.md`.

Build a self-contained x64 executable from Windows PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\apps\desktop\Publish.ps1
```

The output is a single `artifacts/native/SwitchTrade/SwitchTrade.exe`. A standalone copy can display
the UI and report backend status. The installed copy finds `installer/Launch-SwitchTrade.ps1` beside
it, starts the isolated WSL runtime without opening a browser, and talks to the local JSON API at
`http://127.0.0.1:8787`.

Radio and protocol logic does not live in this project. Hardware profiles, drivers, RFU behavior,
and future game features remain replaceable behind the existing control API.
