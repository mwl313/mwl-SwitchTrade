# Hardware support expansion — 2026-08-26

## Outcome

SwitchTrade now has one canonical, WSL-USB-only hardware policy:

- `config/wsl-radio-hardware.tsv` is the source of truth for exact USB ID, driver,
  allowed role, maturity status, engine, model/chipset, and evidence.
- `HostTransport + ldn.create_network()` (`ldn`) is the default and only selectable
  host/AP engine for every card.
- `hostapd` and direct `nl80211` remain visible as **In Development** and fail closed if
  selected. Their prototypes do not yet own the complete Nintendo LDN lifecycle.
- `production-verified` and `beta-candidate` profiles may run normally.
- `upstream-candidate` and `driver-candidate` profiles need explicit consent for each
  attempt (`--allow-experimental-hardware`). They never auto-select.
- `quarantined` profiles cannot run a trading attempt, even with the experimental flag.

This is an expansion of known settings and candidates, not a claim that every listed
card works with a physical Switch. Only physical evidence can promote a card.

## Matrix and evidence

| USB ID | Model / chipset | Linux driver | SwitchTrade status | Basis |
|---|---|---|---|---|
| `0bda:818b` | RTL8192EU | `rtl8xxxu` | beta candidate, auto | Existing SwitchTrade G2–G4, real-Switch trade and RX soak evidence; two-endpoint gate remains |
| `0bda:8179` | RTL8188EU | `rtl8xxxu` / pinned `8188eu` | quarantined | Existing RX evidence plus control-port/AP+monitor failures |
| `0e8d:7610` | ALFA AWUS036ACHM / MT7610U | `mt76x0u` | upstream candidate | Application-specific upstream reports high reliability and says its demo used this model |
| `0e8d:7612` | ALFA AWUS036ACM / MT7612U | `mt76x2u` | driver candidate | Manufacturer documents exact ID and mainline Linux support |
| `148f:2770` | RT2770 family | `rt2800usb` | driver candidate | Exact in-tree driver ID plus manufacturer Linux compatibility |
| `148f:3070` | RT3070 family | `rt2800usb` | driver candidate | Exact in-tree driver ID plus manufacturer Linux compatibility |
| `148f:3572` | RT3572 family | `rt2800usb` | driver candidate | Manufacturer Linux compatibility; requires exact SwitchTrade certification |
| `0bda:c811` | RTL8821CU family | `rtw88_8821cu` | driver candidate | Exact USB ID exists in the upstream Linux `rtw8821cu` table |
| `0cf3:9271` | ALFA AWUS036NHA / AR9271 | `ath9k_htc` | quarantined | Linux supports the card, but application-specific upstream reports frequent IP assignment failure |

Primary sources:

- [frlg-ldn-trade tested-card table and demo card](https://github.com/tornadus/frlg-ldn-trade/blob/main/README.md)
- [ALFA Linux compatibility table](https://docs.alfa.com.tw/Support/Compat/)
- [ALFA MT7610U / AWUS036ACHM details](https://docs.alfa.com.tw/Support/Linux/MT7610U/)
- [ALFA MT7612U / AWUS036ACM details](https://docs.alfa.com.tw/Support/Linux/MT7612U/)
- [Linux `rt2800usb` exact USB device table](https://github.com/torvalds/linux/blob/master/drivers/net/wireless/ralink/rt2x00/rt2800usb.c)
- [Linux `rtw8821cu` exact USB device table](https://github.com/torvalds/linux/blob/master/drivers/net/wireless/realtek/rtw88/rtw8821cu.c)
- [Linux MT7610U Kconfig](https://github.com/torvalds/linux/blob/master/drivers/net/wireless/mediatek/mt76/mt76x0/Kconfig)
- [Linux AR9271/ath9k_htc Kconfig](https://github.com/torvalds/linux/blob/master/drivers/net/wireless/ath/ath9k/Kconfig)
- [Existing SwitchTrade WSL radio evidence](24-wsl-radio-validation-20260824.md)

Internal PCIe/M.2 cards reported by upstream were intentionally excluded: SwitchTrade's
supported Windows deployment path is isolated WSL plus USB/IP-attached external radios.

## Kernel release requirements

The release kernel remains owned and built in the separate authoritative
`mwl313/wsl2-kernel-build` repository. A release that wants to expose all matrix candidates
must enable and package, at minimum:

```text
CONFIG_USB=y
CONFIG_CFG80211=m
CONFIG_MAC80211=m
CONFIG_TUN=m
CONFIG_RTL8XXXU=m
CONFIG_MT76x0U=m
CONFIG_MT76x2U=m
CONFIG_RT2800USB=m
CONFIG_RTW88_8821CU=m
CONFIG_ATH9K_HTC=m
```

The matching firmware must be pinned, checksummed, included in the kernel/rootfs release,
and verified against the exact running kernel. The app repository does not copy arbitrary
modules into production. Its local `scripts/wsl2/build_kernel.sh` accepts these through
`EXTRA_KERNEL_CONFIG` and firmware through `EXTRA_FIRMWARE_SPECS`; release artifacts still
come from the separate kernel repository.

## Enforcement points

Policy is checked independently in all paths so no UI or direct CLI can bypass it:

1. Python runtime planning (`switchtrade.hardware` / `switchtrade.endpoint`).
2. Control API session start, retry, and repair.
3. Windows USB/IP preflight.
4. WSL driver/RX preparation.
5. `HostTransport` itself rejects every engine except `ldn`.

An experimental attempt is explicit and non-persistent:

```bash
sudo scripts/run-beta-endpoint.sh \
  --usb-id 0e8d:7610 \
  --allow-experimental-hardware \
  --tunnel-seat member_a --switch-room-role finder \
  --session-id EXAMPLE --relay-url http://127.0.0.1:8788
```

## Automatic diagnostics

`python -m switchtrade.hardware_diagnostics` emits a redacted
`hardware-diagnostic.v1` report and per-stage command logs. Known failures receive stable
codes and suggested actions; unknown cards can still run read-only checks so their bundle is
useful for extending the matrix.

```bash
# Read-only: WSL, USB visibility, binding, modinfo, firmware/kernel log,
# rfkill, AP/monitor modes, and interface-combination declaration.
sudo bridge/.venv/bin/python -m switchtrade.hardware_diagnostics \
  --usb-id 0e8d:7610 --mode quick

# Adds the existing multi-channel actual-RX gate.
sudo bridge/.venv/bin/python -m switchtrade.hardware_diagnostics \
  --usb-id 0e8d:7610 --mode certify --allow-experimental-hardware

# Also opens and tears down HostTransport + ldn.create_network() locally.
sudo bridge/.venv/bin/python -m switchtrade.hardware_diagnostics \
  --usb-id 0e8d:7610 --mode full --allow-experimental-hardware
```

The Windows Settings screen can run `quick` diagnostics for a selected matrix profile.
The control API exposes `POST /api/v1/hardware/diagnostics`. Diagnostic JSON/text files are
included in the existing redacted support bundle and deliberately exclude captures, RFU
payloads, keys, room codes, tokens, and MAC addresses.

Stable stages cover policy, WSL, USB, driver binding/module, firmware/kernel messages,
rfkill, AP/monitor capabilities and concurrency, actual RX, local LDN room lifecycle,
external beacon observation, physical Switch association, Nintendo control port, and the
encrypted/TAP data plane.

## What software-only diagnostics cannot certify

Even a `full` pass only proves local setup and lifecycle. Without a second independent radio
or a physical Switch it cannot honestly prove:

- that a beacon is visible over the air;
- that the Switch authenticates and receives an IP address;
- Nintendo control-port behavior;
- CCMP data exchange with the Switch;
- an end-to-end Switch-to-Switch trade or soak stability.

Those stages remain `not_tested` in the report. Promotion to beta/production support requires
the existing two-endpoint physical gate, teardown/retry checks, and soak evidence.
