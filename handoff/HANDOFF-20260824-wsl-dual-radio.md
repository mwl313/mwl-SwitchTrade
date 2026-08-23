# HANDOFF — WSL dual-radio stabilization (2026-08-24)

> Branch: `gptsolreview` in all first-party repositories  
> Scope: make RTL8192EU and RTL8188EU usable in WSL2, enforce pre-capture health, and make later
> chipset/driver additions profile-driven.

## 1. Current conclusion

WSL2 is viable for the next real-Switch phase. It is not yet production-certified because G5 local relay and
G6 two-Switch E2E remain. The two owned radios now have distinct supported paths:

| USB ID | WSL driver | Allowed roles | Evidence |
|---|---|---|---|
| `0bda:818b` RTL8192EU | in-kernel `rtl8xxxu` | host, guest, relay | G2/G3/G4, CH1~13, 30-minute RX soak PASS |
| `0bda:8179` RTL8188EU | pinned vendor `8188eu` | guest, relay | G2/G3/G4, CH1~13, external RX/TX and frame-type injection PASS |

The 8188EU mainline path remains a deterministic failure: firmware is found, but MCU start returns `-11`
before a netdev exists. This is specific to WSL USB/IP + mainline `rtl8xxxu`; the card itself works in VMware
and works in WSL with the vendor initialization path.

## 2. Hardware evidence

### RTL8192EU

- Same WSL 6.18.35.2 kernel and usbipd path that fails mainline 8188EU.
- Monitor mode and channel setters 1 through 13 pass.
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
  The warning-free rebuilt artifact is the final driver certification gate.
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

Current Windows ownership: both radios are attached to Ubuntu WSL; VMware USB Arbitrator is stopped but still
Automatic at reboot. VM2 remains reachable by Ethernet/Tailscale with NetworkManager, systemd-networkd, and
tailscaled active, but owns no Wi-Fi USB device.

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

1. Finish warning-free patched 8188EU artifact certification.
2. Run WSL G5 with both cards in one machine and a local relay, measuring loss/latency without internet RTT.
3. Remove saved internet settings from both Switches without enabling airplane mode.
4. Discovery-capture channels 1–13. One hopping radio can miss short frames, so prefer fixed parallel radios or
   repeated sweeps when possible.
5. Run G6 real Switch A↔Switch B framerelay E2E. Record assoc, ACK/retry, relay latency, drops, and trade result.
6. Only after G6 and a repeat soak should the installer/UI call the WSL backend production-ready.

No manual work is required before G5/G6 except putting the two Switches into the requested Direct Connection
screens and removing their saved internet network settings.
