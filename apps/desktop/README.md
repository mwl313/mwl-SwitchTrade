# SwitchTrade native Windows client

This is the product UI. It is a self-contained x64 WPF application and does not use Electron,
Chromium, WebView2, or an external browser.

Build it from Windows PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\apps\desktop\Publish.ps1 `
  -Output .\artifacts\native\SwitchTrade
```

The installed executable starts the adjacent WSL launcher and communicates with the local API at
`http://127.0.0.1:8787`. A standalone copy opens the recovery screen when the installed runtime is
absent. Views render real local/relay state only; no sample rooms, members, hardware, or party data are
substituted.

Architecture, UI flow, contracts, and extension rules are maintained in
[`docs/TECHNICAL_GUIDE.md`](../../docs/TECHNICAL_GUIDE.md). Protocol and radio logic remain outside
this project behind the local v1 API.
