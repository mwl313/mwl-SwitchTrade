# 30 — Native fixed-channel handshake gold and PC-host fix (2026-08-24)

## Outcome

The two-stock-Switch test produced the missing reference capture. Switch A created a new
FRLG room on channel 1, Switch B joined, A confirmed the join, both entered the trading
room, and B later initiated a clean exit that caused both consoles to leave in a neutral
state.

This capture changes the diagnosis from “the radio or Switch did not send the handshake”
to a byte-specific implementation defect:

- the old PC host sent a Net `0x11` with zero station records;
- the native host sends a 132-byte variable station table containing six 22-byte slots;
- the old PC host stopped after parsing the guest join;
- the native host immediately sends Session type `2`, then Session type `5`, and the guest
  answers with Session type `6`.

The capture also proves that the protected data frames are the two Switches communicating
over the LDN room. They are not SK-router traffic: the addresses, link-local subnet, session
key, Pia station IDs, and bidirectional game stream all belong to the native room.

Switch A's internet connection was needed only to pass the software licence check before
launch. The captured trade session itself used the console-created LDN network.

## Capture quality and provenance

Capture directory (kept local and ignored by Git):

`logs/golden/native_fixed_handshake_20260824_live/`

| File | Bytes | SHA-256 |
|---|---:|---|
| `discovery_rtl8188_all24.pcap` | 395,052 | `05670b3512c9b53bcf4cac9862740493ba00170496f7de67975374d6482666e1` |
| `discovery_rtl8192_ch6.pcap` | 620,592 | `4ef25992648c3acb690da4ef4e9a4fa693f509b4e2cf16ec015162a9c808aca1` |
| `fixed_ch1_rtl8188.pcap` | 7,426,521 | `9e0efa267bdcd8f21bace046d756ef3fda7518fbc5cf26ddba4f77b361c7dbbd` |
| `fixed_ch1_rtl8192.pcap` | 6,742,857 | `e6df7e03b2d33c11aaec112306f4605706a11afd9fd35fc9dd97ad768257d0b5` |

Both radios passed the pre- and post-capture actual-RX health gate. The fixed capture
reported zero kernel drops on both radios. RTL8192EU recorded 26,270 packets and RTL8188EU
recorded 53,169 packets. This run therefore provides positive evidence that the patched
RTL8188EU was not in receive-death during the test; it does not change its guest/observer-only
project role because its vendor driver still deadlocks in AP+monitor operation.

The earlier CH11 room and this CH1 room were two room instances. The user explicitly quit
the first room and created a new one, which explains the transition and agrees with the
different SSID/session parameters.

## Native room identity

```text
channel               1
BSSID / Switch A      a4:c1:e8:66:73:25
Switch B              98:41:5c:79:41:38
SSID                   e02543555c30c76b85730a6812224b7c
communication id      0x01006fa0233f8000
scene id               22287
LDN protocol           3
advert format/version  3 / 4
application version    88
server random          33ffd1195263761ef65aabe4f10b71b0
challenge              0x1876ecff91646fe9
subnet                  169.254.25.0/24
host                    169.254.25.1 / a4:c1:e8:66:73:25 / Min
guest                   169.254.25.2 / 98:41:5c:79:41:38 / mwl
```

The verified CCMP and Pia decoders recovered 18,252 Pia datagrams from the RTL8192EU
fixed capture with zero Pia authentication failures. Protocol message counts were Net 4,
Session 5, Reliable 38,534, and RTT 1,860. Multiple Reliable messages may share one Pia
datagram, so the message count is larger than the datagram count.

## Missing handshake, now byte-locked

Times below are relative to the first Net `0x11`.

| Frame | Time | Direction | Pia header | Message | Result |
|---:|---:|---|---|---|---|
| 1250 | 0.000 s | A → broadcast | dst `0000`, src `cdb0`, pkt `0` | Net `0x11`, 162 B | native host station announcement |
| 1254 | 0.020 s | B → A | dst/src `0000`, pkt `0` | Net `0x12`, 8 B | echoes sequence `2` |
| 1255 | 0.049 s | B → A | dst `0000`, src `f469`, pkt `0` | Session `0`, 107 B | guest join request |
| 1259 | 0.064 s | A → B | dst `f469`, src `cdb0`, pkt `1` | Session `2`, 37 B | unicast join response |
| 1260 | 0.065 s | A → broadcast | dst `0001`, src `cdb0`, pkt `1` | Session `5`, 189 B | two-station session update |
| 1262 | 0.084 s | B → A | dst `cdb0`, src `f469`, pkt `1` | Session `6`, 15 B | guest finalize |
| 1264 | 0.119 s | B → A | dst `cdb0`, src `f469`, pkt `2` | Reliable INIT | FireRed metadata; game link starts |

The native Net `0x11` fixed portion contains sequence `2`, host variable ID `cdb0`,
network ID `0000000055c77b2b`, open flag `1`, station capacity `6`, and migrating flag `0`.
Its `size=0x0084` payload contains exactly six NetStation records:

1. host `169.254.25.1:12345`, ranking `0`;
2. guest `169.254.25.2:12345`, ranking `1`;
3. four empty records with ranking `0xff`.

The 8-byte LDN constant ID is not display-order MAC plus two zero bytes. Kinnay's Pia type
definition and the capture agree on this transformation:

```text
constant = mac[2], mac[4], mac[5], mac[3], mac[1], mac[0], 00, 00
A a4:c1:e8:66:73:25 -> e8:73:25:66:c1:a4:00:00
B 98:41:5c:79:41:38 -> 5c:41:38:79:41:98:00:00
```

The Session type `2` and type `5` payloads, channel destination IDs, compression flags,
per-channel packet IDs, and `f469` recipient footers are now locked by unit tests against
the native bytes.

Primary protocol references:

- <https://github.com/kinnay/NintendoClients/wiki/Net-Protocol>
- <https://github.com/kinnay/NintendoClients/wiki/Pia-Types>
- <https://github.com/kinnay/NintendoClients/wiki/Pia-Protocol>
- <https://github.com/kinnay/NintendoClients/wiki/Session-Protocol-(new)>

## Graceful teardown

The user's observed neutral exit is present on the wire:

- at `+147.078 s`, host A sends an emulator Reliable `WD` disconnect;
- at `+147.434 s`, guest B returns the corresponding `WD`;
- at `+149.104 s`, B sends Session type `3` with its station identity/address;
- the Pia stream then stops without a deauthentication storm or capture failure.

This is a valid native teardown reference for the future PC-host engine.

## Implemented fix

The `frlg-ldn-trade-emu` `gptsolreview` branch, commit `be18d57`, now:

- builds the six-record Net `0x11` station table;
- applies the documented LDN constant-ID transformation;
- waits until HostTransport has a real peer before advertising Net `0x11`;
- parses the native Session join, including player IDs;
- emits byte-verified Session type `2` and type `5` responses with native framing;
- recognizes the guest's Session type `6` finalize;
- keeps game traffic gated after Pia finalize because the existing Reliable/RFU engine is
  the guest/child implementation, not a host/parent implementation;
- tests retry/duplicate behavior without allowing a duplicate join to undo a finalized state.

The main repository's radio health gate also now returns success explicitly after a clean
stale-capture check. Without that return, an empty `pgrep` process substitution could make a
healthy workflow fail under `set -e`.

## Verification

```text
py_compile                                    PASS
tests.test_pia_host                           5/5 PASS
all ordinary emulator tests                  123 PASS
full discovery                               one known setup error
known setup error                            optional relay test lacks uvicorn in this venv
```

The `uvicorn` error predates and is independent of the Pia changes.

## Remaining roadblock and next live gate

The next test is a one-Switch PC-host smoke test, not another native two-Switch capture.

2026-08-24 addendum: the first smoke test stopped below Pia because rtl8xxxu returned
hardware-decrypted data with the CCMP wrapper retained; Kinnay double-decrypted and silently
dropped the Switch's ARP. The local compatibility fix and exact boundary evidence are in
`docs/31-pc-host-monitor-ccmp-20260824.md`. Repeat this gate only with that fix active.

Success criteria:

1. Switch sees and joins the PC room.
2. PC sends the six-record compressed Net `0x11`.
3. Switch returns Net `0x12` and Session `0`.
4. PC sends Session `2` and `5`.
5. Switch returns Session `6` and its Reliable INIT metadata.

Only after all five are observed should `HostConnectionManager.connected` be released.
The next implementation then needs a host/parent Reliable and RFU path. The native reference
starts with guest INIT metadata, host bulk ACK, guest `WC` connect, then host `WA` accept plus
bulk ACK. Reusing the current child `_drive_reliable()` would invert those roles and is therefore
intentionally blocked.
