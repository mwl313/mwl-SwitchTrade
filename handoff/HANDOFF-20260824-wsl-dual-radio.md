# HANDOFF — WSL dual-radio stabilization (2026-08-24)

> **Superseded capability conclusion (2026-08-25):** later real-Switch guest tests proved that
> RTL8188EU RF RX/TX success did not establish LDN guest support. Its patched driver fails Nintendo's
> custom nl80211 control-port association with `EINVAL`, and AP+monitor remains unsafe. Treat 8188EU
> as observer/driver-research only. The current plan is
> `docs/49-production-beta-priorities-20260825.md`.

> Branch: `gptsolreview` in all first-party repositories.
> Scope: make RTL8192EU and RTL8188EU usable in WSL2, enforce pre-capture health, and make later
> chipset/driver additions profile-driven.

## 1. Current conclusion

WSL2 is viable for the next real-Switch phase. It is not yet production-certified because G5 local relay and
G6 two-Switch E2E remain. The two owned radios now have distinct supported paths:

| USB ID | WSL driver | Allowed roles | Evidence |
|---|---|---|---|
| `0bda:818b` RTL8192EU | in-kernel `rtl8xxxu` | host, guest, relay | G2/G3/G4, CH1~13, 30-minute RX soak PASS |
| `0bda:8179` RTL8188EU | pinned vendor `8188eu` | observer only (2026-08-25 correction) | RF G2/G3/G4 PASS, real guest control-port connect FAIL |

The 8188EU mainline path remains a deterministic failure: firmware is found, but MCU start returns `-11`
before a netdev exists. This is specific to WSL USB/IP + mainline `rtl8xxxu`; the card itself works in VMware
and works in WSL with the vendor initialization path.

## 2. Hardware evidence

### RTL8192EU

- Same WSL 6.18.35.2 kernel and usbipd path that fails mainline 8188EU.
- Monitor mode and channel setters 1 through 13 pass.
- A temporary `__ap` interface came up while the monitor interface stayed active. This proves low-level
  AP+monitor vif coexistence in WSL, but not yet `hostapd` beaconing or a Switch join.
- External WSL→VM RF injection: 28/30 and 90/100 unique broadcast probes; every captured bare frame byte-exact.
- Final soak: 30:00, 41,394 captured, 41,396 received by filter, zero kernel drops.
- Post-soak actual-RX health gate passed.
- Soak pcap SHA256: `33812026ce5cbbe9459887923e00a898d6045d54332c99e52f9de0da48f22490`.

### RTL8188EU

- Mainline failure reproduced on WSL kernels 6.6.87.2, 6.6.123.2, and 6.18.35.2.
- Vendor source pinned to `SimplyCEO/rtl8188eus` commit
  `b5f02e742fad6ae27d893ffae62d05e27374c0ed` and built against the exact running kernel.
- Vendor WSL actual RX passed. External 8192→8188 RX saw 86/100 unique exact frames; the receiver added
  valid four-byte FCS. Reverse 8188→8192 TX saw 98/100 unique; only 802.11 Sequence Control was driver-owned.
- 25 each of probe request, vendor action, beacon, and data were injected. External capture saw 24, 24, 25,
  and 25 respectively, with zero kernel drops. Addresses and payloads were preserved; Sequence Control and
  beacon timestamp are expected device-owned over-air fields.
- The first vendor artifact produced a Linux 6.18 `Incorrect netdev->dev_addr` warning on interface open.
  Kernel-build commit `1650687` replaces all six direct netdev address writes with `eth_hw_addr_set()`.
  Action run `32654325060` produced the warning-free artifact (SHA256
  `032002aaf8ce5c25cdf1482eee085c2bfa002d0f780b05cd8e14b7905c9b7d21`, srcversion
  `0E89F9AAD0AC20A979DE5B4`). Two clean loads and actual RX passed with zero address warnings.
- Single-interface AP works: `hostapd` reached `AP-ENABLED`, and the independent 8192EU captured 108 matching
  beacons with zero kernel drops. Simultaneous AP+monitor is unsafe: add/delete operations deadlock in the
  vendor `cfg80211_netdev_notifier` and require a WSL restart. The card therefore stays guest/relay-only for
  this project even though its hardware can operate as a standalone AP.
- Patched-driver five-minute soak: 8,474 captured, 8,476 received by filter, zero kernel drops; post-soak
  actual RX passed. Capture SHA256: `2a321fed8d5eb3a629d08c067680cac1633723cfae609cc25227fb3a18c6d318`.
  Its profile state is `verified-guest-relay`; the 30-minute evidence still belongs only to the 8192EU.
- `usb ... seqnum max` is informational, not an error: `vhci_hcd` prints it when the USB/IP URB counter reaches
  `0xffff`. Traffic continued and both health/TX tests passed afterward.

## 3. Runtime safety implementation

- `config/wsl-radio-hardware.tsv`: USB ID, driver strategy/module, allowed drivers, roles, state, notes.
- `scripts/wsl-radio-prepare.sh`: deterministic device choice; vanilla/vendor fallback; vermagic, SHA256 and
  loaded-module `srcversion` validation; driver and role enforcement; actual-RX gate; command exec.
- `scripts/radio-health-gate.sh`: exact USB ID support and exports both selected interface and USB ID.
- `scripts/run_trade.sh v7`: WSL selector is always in front of a trade. Multiple radios require explicit ID;
  host mode requires the profile's host role.
- `scripts/windows/wsl-radio-preflight.ps1`: detects VMware Arbitrator conflicts, missing usbipd attachment,
  missing WSL enumeration, and wrong kernel. Elevated `-Prepare -AutoAttach` stops VMware USB ownership for
  the current session, attaches profiled cards, and starts hidden usbipd reattach watchers. It does not alter
  the service's Automatic start type.
- `.wslconfig`: `instanceIdleTimeout=-1` and `vmIdleTimeout=-1` prevent a healthy background capture/relay
  from being terminated by WSL idle shutdown.
- WSL now has the pinned emulator requirements in `emu/.venv`, `hostapd`, and the exact VM2-tested
  `prod.keys` installed at `/root/.switch/prod.keys` with mode 0600. `ldn.load_keys()` and the wrapper's
  default `.venv`/USB/phy dry-run all pass. The older repository backup key differed and was not used.
- `run_trade.sh` explicitly loads `ccm`, `cmac`, and `tun`; WSL did not autoload these modules and otherwise
  failed late at static CCMP key installation or `/dev/net/tun`. The 8192EU subsequently opened a real
  `HostTransport` room through AP+monitor/TAP and advertised the FRLG communication ID successfully.
- The selector recreates a missing monitor netdev, prefers monitor when a device has several vifs, and removes
  stale extras. This also fixes a prior multi-vif `pipefail`/`head -1` SIGPIPE exit. `HostTransport.stop()` now
  waits the full teardown grace and sweeps its exclusive phy after the thread exits; post-test `iw dev` was empty.

Current Windows ownership: both radios are attached to Ubuntu WSL; VMware USB Arbitrator is stopped but still
Automatic at reboot. VM2 remains reachable by Ethernet/Tailscale with NetworkManager, systemd-networkd, and
tailscaled active, but owns no Wi-Fi USB device. Re-run the elevated Windows preflight after either a reboot or
`wsl --shutdown`; the watcher processes do not survive a full WSL shutdown.

## 4. Software audit fix

`RelayBridge` was adding radiotap before calling `MonitorRadio.send()`, which adds radiotap itself. The fake
radio tests modeled the wrong contract and missed the double header. Emulator commit `82dd0d3` now passes bare
802.11 frames to `MonitorRadio`; a regression test asserts exactly one radiotap header. The focused Linux suite
passes 58/58. The repository-wide discover ran 115 assertions successfully; the sole setup error was the known
standalone-clone layout assumption in `test_relay_offline` (`relay/` lives in the parent SwitchTrade checkout),
not a product assertion failure.

## 5. Extending to a new chipset

1. Add a `candidate` row to the TSV profile.
2. For an in-kernel driver, supply `CONFIG_DRIVER=m` through the kernel workflow's `extra_kernel_config` and
   any required firmware through `extra_firmware`.
3. For an out-of-tree driver, pin source commit + project patch, build against the exact kernel, and ship module
   plus SHA256 sidecar.
4. Run G2 interface creation, G3 actual RX, G4 external RX/TX, 30-minute soak, then real role-specific tests.
5. Expose only passed roles and change the profile state to `verified`.

Unknown hardware is rejected; a module merely loading is never treated as compatibility proof.

## 6. Next test, in order

1. Run WSL G5 with both cards in one machine and a local relay, measuring loss/latency without internet RTT.
2. Remove saved internet settings from both Switches without enabling airplane mode.
3. Discovery-capture channels 1–13. One hopping radio can miss short frames, so prefer fixed parallel radios or
   repeated sweeps when possible.
4. Run G6 real Switch A↔Switch B framerelay E2E. Record assoc, ACK/retry, relay latency, drops, and trade result.
5. Only after G6 and a repeat soak should the installer/UI call the WSL backend production-ready.

No manual work is required before G5/G6 except putting the two Switches into the requested Direct Connection
screens and removing their saved internet network settings.
