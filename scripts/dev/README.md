# Development source hot-deploy

The root dispatcher provides source-only development commands:

```powershell
.\dev.ps1 doctor
.\dev.ps1 sync
.\dev.ps1 run -- <python arguments>
.\dev.ps1 test -- <pytest arguments>
.\dev.ps1 clean
```

`doctor` reads `%LOCALAPPDATA%\SwitchTrade\state\active-runtime.json`, proves the named WSL
distro and SwitchTrade ownership marker, checks the installed virtual-environment Python, and
compares the two requirements hashes. It never repairs or installs anything. A mismatch returns
`DEV_DEPENDENCY_MISMATCH`; pip, apt, Repair, Install, and Update are never automatic fallbacks.

`sync` packages only the paths in `dev-source-allowlist.txt`, including eligible untracked source,
and excludes credentials, machine state, caches, artifacts, captures, support bundles, archives,
installer payloads, and kernel payloads. It derives a content ID from sorted relative paths and
SHA-256 hashes, verifies the extracted files inside WSL, commits a new immutable release below
`/opt/switchtrade-dev/releases/`, and atomically switches `/opt/switchtrade-dev/current`.

Every WSL process uses the discovered distro, root user, explicit Linux cwd, installed Python at
`/opt/switchtrade/bridge/.venv/bin/python`, and the overlay environment variables. The production
root `/opt/switchtrade` is read-only to this workflow. `clean` is the only command that removes
anything, and it is limited to `/opt/switchtrade-dev`.

An interrupted sync may leave a staging directory or lock. Do not delete it by guesswork: inspect
the exact overlay identity and use the owning runtime's recovery path. `DEV_DEPLOY_BUSY` means the
lock was not acquired; `DEV_ARCHIVE_FAILED`, `DEV_EXTRACT_FAILED`, `DEV_MANIFEST_MISMATCH`, and
`DEV_COMMIT_FAILED` retain the failed boundary rather than silently switching `current`.

This workflow is development validation only. It does not change installer/package behavior,
production runtime files, WSL registration, kernel, drivers, firmware, USB ownership, or physical
qualification status.
