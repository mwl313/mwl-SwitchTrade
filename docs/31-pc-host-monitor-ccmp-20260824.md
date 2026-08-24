# 31 — PC-host join failure: rtl8xxxu retained CCMP wrapper (2026-08-24)

## Outcome

The first one-Switch test of the corrected PC-host Pia implementation still showed
"awaiting CODEX's response" and then "the other trainer appears unavailable." This was
expected to implicate Pia, but the Pia fix was never reached. The failure was below UDP:

1. the Switch discovered, authenticated with, and associated to the PC room;
2. it sent a Nintendo authentication/control frame and seven ARP requests for the PC;
3. RTL8192EU received all eight data frames at about -45 dBm;
4. Kinnay discarded them before writing them to `ldn-tap`;
5. the PC therefore sent no ARP reply, the Switch could not address Net `0x12`, and it
   disconnected after about 6.5 seconds.

This rules out weak signal, RTL8188EU receive death, missing RF traffic, and the corrected
Net/Session bytes as causes of this specific UI failure.

## Boundary capture

Local evidence directory (ignored by Git):

`logs/golden/pc_host_bridge_diag_20260824_141144/`

| File | Bytes | SHA-256 |
|---|---:|---|
| `host_final_ldn_mon.pcap` | 3,065,055 | `8a2671a1e12ed932a0bd479c33ecd4dec39ab69fcbf8bb8f810a462ece5e3d52` |
| `host_ldn_tap.pcap` | 7,129 | `d5a9131d90027d35845d0dd4943b6c86d077addb23dbb1d15507054c869960b5` |
| `host_ap_netdev.pcap` | 24 | `704e5e5b3234433c01fcfd1b20a306e77e985038120492dc53965c3edd38a4ea` |
| `observer_rtl8188_ch6.pcap` | 3,843,979 | `159736652dd5ec6a1866cc4304695f9292e2b0113c4782f455848e6f9b43f3ec` |
| `pc_host_pia.jsonl` | 16,446 | `cc95fd677a3e68b25bb44895430c7bf33c29eb312ca5f74bcc645c3c580dd06b` |

Both cards passed the actual-RX health gate before capture. The host monitor captured 10,707
packets and the RTL8188EU observer captured 20,399; both reported zero kernel drops.

```text
PC BSSID / monitor MAC    a0:47:d7:b0:2b:39
Switch MAC                98:41:5c:79:41:38
channel                   6
subnet                    169.254.14.0/24
PC                        169.254.14.1
Switch                    169.254.14.2
```

The host's final `ldn-mon` saw eight Switch data frames: one LDN control frame with SNAP
ethertype `0x88b7` and seven broadcast ARP requests asking for `169.254.14.1`. The TAP capture
contains no inbound ARP at all. It contains only locally generated IPv6 router solicitations
and the PC's outgoing Pia Net `0x11` broadcasts. The Pia JSONL likewise contains 43 outgoing
UDP records and zero inbound records.

## Exact driver/library incompatibility

The RTL8192EU `rtl8xxxu` monitor vif returned the Switch frames in this form:

```text
802.11 Protected flag = 1
8-byte CCMP header retained
payload already decrypted and begins aa aa 03 (SNAP)
8-byte CCMP MIC retained
```

Kinnay `ldn` 0.0.17 already handles a driver that returns plaintext SNAP and clears the
entire CCMP wrapper. It does not handle the observed retained-wrapper variant. Its
`DataFrame.decode()` therefore marks the frame encrypted, and `APNetwork._process_data_frame()`
tries AES-CCM decryption a second time. Authentication fails because the payload is already
plaintext. `_receive_data_frames()` catches every exception and silently ignores it.

The intended Kinnay architecture is AP + monitor + TAP specifically because the AP netdev
does not provide the required broadcast receive path. Bypassing the monitor is therefore not
a valid fix; normalizing the driver's monitor representation is.

## Implemented compatibility fix

The emulator `gptsolreview` branch, commit `a740440`, now installs a guarded runtime adapter
before `ldn.create_network()`:

- site-packages remains untouched;
- after stock decode, a protected frame whose post-CCMP payload starts with SNAP is recognized
  as hardware-decrypted;
- the retained 8-byte MIC is removed and `protected` is cleared;
- true ciphertext remains on Kinnay's normal decrypt path;
- the behavior is idempotent and emits one activation log line.

Focused tests cover both the retained-wrapper plaintext case and the unchanged ciphertext
case. An offline replay of the exact host-monitor pcap produced:

```text
switch_data=8
snap_deliverable=8
arp_deliverable=7
```

The focused host suite is 23/23 PASS, including advertisement, beacon-head, teardown, Pia,
and monitor-CCMP compatibility tests.

Full discovery has 125 ordinary PASS results. Its sole error is the pre-existing optional
relay environment check because this venv does not contain `uvicorn`; it is unchanged and
independent of the radio fix.

## Live status and next gate

The unchanged diagnostic room reproduced the expected unavailable message. A later patched
room advertised for about eight minutes but received no Switch join attempt, so it was closed;
that run is not evidence of either live success or live failure.

The next test needs one manual action: keep one Switch on Join Room, select `CODEX` once after
capture-ready notification, and report the first UI state after "awaiting CODEX's response."
Required wire progression:

```text
Switch ARP request -> ldn-mon -> ldn-tap
PC ARP reply       -> ldn-tap -> ldn-mon -> Switch
PC Net 0x11        -> Switch Net 0x12 + Session 0
PC Session 2/5     -> Switch Session 6 + Reliable INIT
```

If ARP passes but Pia does not, continue with the byte-locked Session analysis in
`docs/30-native-fixed-handshake-20260824.md`. Do not implement host/parent Reliable until
Session `6` and the first guest Reliable INIT are observed live.
