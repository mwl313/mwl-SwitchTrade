# SwitchTrade beta package

The bootstrap is deliberately split from the WSL kernel decision. It installs and provisions only the
named `SwitchTrade` distribution and never edits the user's global `.wslconfig`.

## Build

1. Install the pinned test/runtime dependencies under Python 3.12 or newer.
2. In `ui`, run `pnpm build:desktop`.
3. Commit the exact source being packaged; the builder refuses a dirty worktree.
4. Run `installer/Build-Package.ps1`.

Pass `-Rootfs PATH` to include a versioned minimal WSL rootfs. Without it, the resulting archive is an
internal upgrade/repair package for a machine that already has the `SwitchTrade` distro; a clean
install intentionally fails with an exact missing-rootfs error.

## Setup safety

- `SwitchTradeSetup.ps1 -Action Audit` is read-only.
- `Install` and `Repair` provision the isolated distro and retain the previous `/opt/switchtrade`
  runtime for rollback.
- `Uninstall` removes application files only.
- The distro is unregistered only when `Uninstall -PurgeDistro` is explicitly requested.
- Neither setup nor launch changes the custom/stock WSL kernel selection.

The localhost relay default is for internal same-machine validation. A cross-network beta must supply
a reachable HTTPS relay URL in the installed `config.json`.
