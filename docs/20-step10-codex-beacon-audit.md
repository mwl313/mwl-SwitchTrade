# 20 — STEP 10 Codex audit: LDN discovery correction and fixes (2026-08-23)

## Outcome

The project was debugging the wrong discovery signal. A Nintendo Switch does not build its
LDN room list from ordinary 802.11 beacons or Probe Requests. The host broadcasts an encrypted
Nintendo Vendor Action advertisement every 100 ms, and the client passively scans those frames.
Only after the advertisement has been accepted and the user selects the room does normal
open-system authentication/association begin.

Primary source: [Kinnay NintendoClients — LDN Protocol](https://github.com/kinnay/NintendoClients/wiki/LDN-Protocol).
The LDN maintainer also states that a Switch never sends a frame to an AP before it has received
an Action advertisement: [kinnay/LDN PR #8](https://github.com/kinnay/LDN/pull/8#issuecomment-3938931613).

Therefore `docs/19-step10-아웃라인과-픽스.md` P0 (wait for Probe Request/Auth) cannot distinguish
"not seen" from "seen but rejected": no Probe Request is expected while the room is absent from
the list.

## Confirmed defects in `frlg-ldn-trade-emu` at `8ebe5dd`

| Severity | Defect | Evidence | Fix |
|---|---|---|---|
| Critical | BSS SSID encoded as 16 raw bytes | LDN passes `param.ssid.hex()` as the 32-character Wi-Fi SSID, but the monkey-patch called `bytes.fromhex()` and advertised the raw 16-byte value. The Action advertisement and probe response therefore described a different SSID than the beacon. | Preserve the 32 ASCII hex characters. |
| Critical | Wrong FRLG capacity (`1/8`) | Every captured real FRLG advertisement in docs/07 and docs/11 is `1/6`; `HostTransport.MAX_PARTICIPANTS = 8` came from the LDN library default, not a capture. This changes the encrypted Vendor Action payload used by the game filter. | Set `MAX_PARTICIPANTS = 6`. |
| High | LDN hidden network changed to visible | Nintendo documents that the SSID is zeroed in beacons. The removed monkey-patch forced `HIDDEN_SSID=NOT_IN_USE`; the complete beacon head also embedded the real SSID. | Keep Kinnay's stock `ZERO_CONTENTS` policy and emit a zero-filled 32-byte SSID IE. |
| High | Beacon capability disagreed with Kinnay's encrypted BSS | Custom value `0x0431` differed from Kinnay's encrypted probe response (`0x0511`). | Use `0x0511` and retain the matching RSN/CCMP IE. |
| Medium | Pia header fields were guessed as flags/TLV | Offsets `0x15:0x17` are player-limit fields; `0x17` is a big-endian u32 name length; `0x1B` is encoding; `0x1C` is the 64-byte name. | Build the documented fixed Pia 6.x structure. |
| Diagnostic gap | Vendor Action was observed only on the transmitting card | Same-radio monitor capture proves local injection/loopback, not RF delivery to the Switch. VM2 external reception was never recorded as a decoded LDN advertisement. | Added `python -m frlgsim.advert_check` for VM2. |

The complete beacon-head workaround is retained because it is the change that made rtl8xxxu
start periodic beaconing. The separate START_AP monkey-patch was deleted: its only effective
change was to make the SSID visible, which contradicts LDN.

## Wire-level offline verification

`tests/test_host_advertisement.py` constructs the real Kinnay `APNetwork`, encodes its complete
encrypted Vendor Action advertisement, decrypts it through Kinnay's decoder, and asserts:

```text
OUI/protocol/type = 7f 00 22 aa 04 00 01 01
comm_id           = 0x01006fa0233f8000
scene_id          = 22287
LDN/security      = version 4 / security level 1
accept policy     = 0
participants      = 1/6
application_data  = 122 bytes, Pia prefix 00 5c 16 00 58
Wi-Fi SSID        = 32 ASCII hex chars, zero-filled in the hidden beacon IE
```

This verifies the bytes produced by the code, not radio delivery.

## Decisive VM1/VM2 test

1. Deploy the modified `frlgsim/` and start HostTransport on VM1, channel 6.
2. Reset VM2's radio, remove stale VIFs, and identify its current PHY.
3. On VM2, from the updated emu checkout, run:

```bash
sudo timeout --signal=INT 15s .venv/bin/python -m frlgsim.advert_check \
  --keys /root/.switch/prod.keys --phy <VM2_PHY> --channel 6
```

Keep the outer `timeout`: Trio cannot cancel a driver call stuck in uninterruptible kernel state.
Do not run this on VM1/the hosting radio; the result must come from a physically separate receiver.

Expected output:

```text
bssid=... ch=6 comm=0x01006fa0233f8000 scene=22287 ldn=v4/security1 \
appver=1 participants=1/6 appdata=122B OK
PASS: external radio decoded the exact FRLG Vendor Action advertisement
```

Interpretation:

- `no decodable ... advertisement`: the blocker is Action-frame RF injection/channel/radio state.
  Ordinary beacon counts are irrelevant until this passes.
- `MISMATCH=...`: Action frames reach VM2, but the encrypted network metadata is wrong; fix the
  named field before testing the Switch.
- `PASS`: put the Switch on the FRLG search screen. If the room is still absent, capture the VM1
  advertisement and a real Switch-host advertisement externally and compare their decoded
  `NetworkInfo` plus all 122 application-data bytes. Do not wait for Probe/Auth yet.
- Room appears but join fails: only then move to Probe Response, open Auth, Assoc, static CCMP key,
  and LDN custom authentication tracing.

## Hostapd branch audit

The current `use_ap_engine=True` path is not an LDN hybrid and must not be used for this test:

1. `async with engine` starts hostapd, then the body calls `engine.start()` again.
2. It bypasses `ldn.create_network()`, so it creates no LDN monitor/TAP, sends no Vendor Action
   advertisements, performs no Nintendo custom authentication, assigns no LDN participant/IP,
   and performs no monitor↔TAP CCMP processing.
3. `_require_tap()` must consequently fail because `ldn-tap` was never created.
4. `AP-STA-CONNECTED` proves only standard 802.11 association, not LDN authentication.
5. Its standard WPA2 mode performs a normal four-way handshake and is not a substitute for LDN's
   static CCMP/custom-auth path.
6. It picks the first `wlx*`/`wlan*`, not the interface belonging to the requested PHY.

The repository already defaults this branch off. A real hostapd hybrid would need hostapd to own
only standard AP management while the existing LDN core continues to own Action advertisements,
custom auth, participants, static keys, monitor mode, and TAP. That is a separate architecture
change; it is not required to test the corrected pure-nl80211 path, which already emits periodic
beacons on the current rtl8xxxu setup.

## Verification completed locally

- Python 3.14 `compileall`: pass.
- 108 non-radio unit tests: pass.
- 4 relay integration tests: pass.
- Kinnay wire encode/decode test: pass.
- `test_detect_phy.py` was not run on Windows because it intentionally constructs Linux sysfs
  symlinks containing `:`; it is unrelated to the host advertisement changes and must be run on
  Linux/VM before deployment.

## Live verification on VM1/VM2 (2026-08-23, Aria)

Deployed the `gptsolreview` branch to both VMs and ran the decisive test:

- VM1: `HostTransport` room open with the corrected code
  (SSID fix + MAX_PARTICIPANTS=6), channel 6, beacon-head override active.
- VM2: physically separate 8188EU receiver, `advert_check` against phy15.

Result: **PASS ×6 consecutive runs** (3 free-scan + 3 fixed-channel),
every run decoded the exact FRLG Vendor Action advertisement:

```text
bssid=A0:47:D7:B0:2B:39 ch=6 comm=0x01006fa0233f8000 scene=22287 \
ldn=v4/security1 appver=1 participants=1/6 appdata=122B OK
PASS: external radio decoded the exact FRLG Vendor Action advertisement
```

One early free-scan run reported `ch=1`: the receiver card caught the
advertisement while still hopping; with channel 6 pinned every run reports
`ch=6`. This is a receiver-state artifact, not host behavior.

G0/G1 gates from this audit are therefore PASSED on real hardware:
periodic beacons (earlier measurement, 102/12s) AND external decoding of the
encrypted LDN Vendor Action advertisement. The next step per §7 is putting a
real Switch on the FRLG search screen while the room is up.
