# Control-first startup and relay diagnosis — 2026-08-26

## User-visible symptoms

After a successful install, the native client opened its recovery screen and said that the installed
local service did not respond. Public Rooms was also unavailable.

These were two independent failures:

1. the installed WSL runtime was healthy, but the Windows launcher did not start its control service;
2. the configured production relay hostname had no resolvable DNS record.

## Local startup root causes

The installed `SwitchTrade` distro was running, `/opt/switchtrade` and its Python environment were
valid, and direct control-service startup passed `app-readiness.v1`. The daily launcher nevertheless
failed before that point because it passed PowerShell named parameters through a positional string
array. Windows PowerShell rejected `-Prepare` as a positional argument.

Two secondary defects would still have caused unreliable startup after that correction:

- the WPF client allowed only about 2.8 seconds for readiness, while a normal cold launch measured
  about 4 seconds;
- the WPF process awaited redirected stream EOF even after the launcher exited, but a background WSL
  process could retain inherited pipe handles and keep the UI waiting indefinitely.

The launcher also ran USB/radio preparation before starting the control plane. This made a missing or
unattached adapter prevent the user from opening the app, Settings, diagnostics, or online rooms even
though the production connection path already has its own adapter selection, attach, driver setup,
and mandatory radio health gate.

## Corrections in `125fbac`

- Daily launch is control-first: it validates installed configuration and starts the local control
  service without attaching or mutating USB radios.
- Adapter attach, driver selection, and the RX health gate remain mandatory at the actual
  `connect_trade_room` session boundary.
- The launcher writes timestamped startup stdout/stderr logs under
  `%LOCALAPPDATA%\SwitchTrade\logs\startup` and reports an early service exit with a bounded tail.
- WPF awaits the launch operation, uses bounded cancellation/retry behavior, and preserves compact
  diagnostics on real failure.
- WPF does not wait indefinitely for inherited stdout/stderr handles after a successful launcher exit.
- Startup polling and the status timer cannot race each other.

This separates three states that the product must not conflate: the local control plane, the online
relay, and the selected radio/Switch session.

## Why Browse Public Rooms is unavailable

The installed client's local readiness endpoint is healthy. However, its relay capability list is
empty because `relay.pangyostonefist.org` currently returns NXDOMAIN. Direct relay health and OpenAPI
requests therefore cannot reach a host. The apex domain returns only its authoritative DNS metadata;
there is no usable relay hostname record.

The client cannot repair an external DNS zone. The relay operator must restore the DNS record to the
deployed relay origin, verify its TLS certificate and `/health` response, and confirm that health
advertises `public-directory.v1`. The existing UI will then enable Browse Public Rooms automatically.

The client now exposes this accurately as relay axis `failed`, code `relay.unavailable`, and displays:
`Public rooms are unavailable while the online relay is offline.` It no longer describes this as an
incompatible local runtime or a failed WSL startup.

## Verification

- Product/installer regression suite: 86 passed
- Native WPF Release build: 0 warnings, 0 errors
- Native setup progress bootstrap build: 0 warnings, 0 errors
- Corrected launcher, unrelated working directory, no radio attached: exit 0; control ready and
  version-compatible
- Actual `beta-125fbac` Update on the non-ASCII-profile development PC: PASS
- Installed WPF self-test: PASS
- Actual installed EXE launch: PASS; UI Automation reached Home and showed the specific relay-offline
  message
- Package schema-2 integrity, Setup Audit, WPF self-test, and sibling ZIP checksum: PASS

## Candidate

- Package: `SwitchTrade-unsigned-private-beta-125fbac.zip`
- SHA-256: `3ac85518f63e118c5f5d44ae6797ad30d72de1d302fe13984c4761b0c6f0cb23`
- Signing: explicitly unsigned private beta

Repository-controlled startup behavior is corrected and exercised on the development PC. Release
approval still requires relay DNS/TLS restoration and the external clean-machine, reboot/resume,
two-PC/two-Switch, and WAN fault/recovery qualification listed in `docs/55`.
