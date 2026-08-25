# Private beta release baseline — 2026-08-25

> Status: frozen as the implementation and final-design baseline.
> Target release: `0.2.0-beta.1` after Gate 0 closes and the contracted backend is integrated.

This document fixes the product claims that the final UI overhaul and later installer must present. It
does not declare the beta ready and does not authorize installer work before the preflight gates permit
it.

## 1. Product and visual identity

- Product name: **SwitchTrade**.
- Visual direction: **Linkline**, a modern native Windows experience implemented in WPF.
- The Emerald web kit under `assets/ui` and `apps/web` is retired reference material. It is not the
  production visual authority and must not be reintroduced by the final overhaul.
- Public room browsing remains clearly labeled **Demo Preview** until the authoritative public service is
  implemented and approved.

The public icon, final logo asset treatment, legal notice text, privacy notice URL, and support contact
still require owner/GPT review before Gate 0 closes.

## 2. Supported platform claim

The private-beta qualification target is:

- Windows 11 24H2 x64;
- WSL 2 with the project-pinned distribution/runtime setup;
- the project custom WSL kernel version documented by the future installer manifest;
- a pinned, tested `usbipd-win` version;
- current Nintendo Switch system and Nintendo Switch Online GBA application versions tested at release.

Windows 10, ARM64 Windows, arbitrary existing WSL distributions, Hyper-V/VMware passthrough, and stock
WSL kernels are not supported claims for this beta unless later qualification adds them.

The installer must warn clearly that selecting the project custom kernel changes the machine-wide WSL
kernel setting and must provide backup, rollback, and ownership messaging. The SwitchTrade WSL
distribution, configuration, data, and lifecycle otherwise remain isolated from user distributions.

## 3. Hardware policy

Primary private-beta hardware:

- Realtek RTL8192EU, USB ID `0bda:818b`;
- two qualified adapters per two-endpoint local test/deployment where the selected topology requires
  independent radios.

The RTL8188EU/`0bda:8179` remains quarantined from the reliable production path until its receive-death
and driver lifecycle behavior pass the same qualification gates. It may appear only as unsupported
diagnostic hardware.

Hardware support remains profile-driven through `config/wsl-radio-hardware.tsv` and the driver/runtime
modules. Adding a chipset should require a new hardware profile, driver package or kernel capability,
health gates, and qualification evidence—not a rewrite of lobby, UI, RFU, or relay code.

## 4. Feature boundary

The beta targets:

- two authenticated people in one private Trade Room;
- either member may create the physical Switch room for each connection attempt;
- automatic radio-role assignment and guided connection steps;
- opaque switch-to-switch RFU forwarding through the relay;
- one complete FireRed/LeafGreen trade cycle with recovery and support diagnostics;
- passive, non-blocking local party views when valid decoder data exists;
- fail-closed successful-trade recognition;
- optional externally consented committed-trade statistics after legal/security approval.

Battles, Union Room expansion, production public matchmaking, RTL8188EU support, quality-of-life jitter
work, broad chipset support, and graceful final visual polish beyond the approved beta UI are backlog,
not hidden beta claims.

## 5. Version boundaries

- Source currently remains `0.2.0-beta.0`/`0.2.0` while the contracts are unimplemented.
- Promote every component to `0.2.0-beta.1` together only after the authoritative room/local API,
  endpoint role split, and final approved WPF integration pass internal tests.
- The desktop, local runtime, RFU envelope, room-control, party-commit, privacy-statistics, kernel, driver
  bundle, and installer versions are separately reported in diagnostics.
- A major local contract mismatch blocks connection and directs the user to Update or Repair.

## 6. Configuration and secret boundary

- Non-secret hardware and behavior defaults ship as versioned project configuration.
- Room/member/reconnect tokens, service credentials, and consent credentials never ship in source or WPF
  settings and are redacted from support bundles.
- Nintendo prod keys are not required for the product and must never be requested, installed, copied, or
  logged.
- User WSL distributions, files, Tailscale configuration, and unrelated USB bindings remain untouched.

## 7. Diagnostics and support baseline

Every private-beta build must provide:

- one user action to collect a redacted support bundle;
- component and contract versions, Windows/WSL/kernel/usbipd versions, detected USB IDs, selected hardware
  profile, health-gate results, room/attempt phase history, reconnects, and typed error codes;
- no room credentials, member/reconnect tokens, raw RFU payloads, session keys, full Pokémon party data,
  raw IP addresses, or unrelated machine inventory;
- a documented operator path for submitting the bundle and identifying its app-generated location.

Final support URL/contact and privacy/legal links remain a Gate 0 owner decision. A placeholder must not
be presented as a working support destination in a release candidate.

## 8. Exit from this baseline

Before implementation proceeds to installer packaging:

1. the owner/GPT approves the final WPF UX, icons/assets, copy, notices, and support destination;
2. Gate 0 in `docs/55` has no open item;
3. the authoritative server/local contracts are implemented and internally verified;
4. hardware qualification, recovery, privacy, security, and release gates are completed in order.
