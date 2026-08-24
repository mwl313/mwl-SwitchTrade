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

## Patched live validation — PASS

The next health-gated live attempt crossed the entire gate even though the Switch UI still
ended with "trainer unavailable." Local evidence is under
`logs/golden/pc_host_ccmp_fix_live_20260824_144343/`:

| File | Bytes | SHA-256 |
|---|---:|---|
| `host_final_ldn_mon.pcap` | 1,595,652 | `52b568a4bf3cf0887ce892798b953140635ad0810f1df43f2177d90be500529d` |
| `host_ldn_tap.pcap` | 15,119 | `c1b89e84f9e874cdaa65fa5218507ed920a004e3e18ccf68f7886c4339a5156c` |
| `observer_rtl8188_ch6.pcap` | 1,499,533 | `734ce777fcbef62f458d016269fe5c61dc4a26ac44028e4b6583c3b14b7dc564` |
| `pc_host_pia.jsonl` | 33,819 | `c417e278c3309acbb3f55fe2725b1265fcadf4797e23d571d62118ba7ff53844` |

The host and observer captured 5,376 and 5,835 packets respectively, both with zero kernel
drops. TAP proves the previously missing transition:

```text
Switch ARP request  who-has 169.254.72.1
PC ARP reply        169.254.72.1 is-at a0:47:d7:b0:2b:39
Switch Net 0x12
Switch Session 0
PC Session 2 + 5
Switch Session 6
Switch Reliable INIT metadata (FireRed, seq fff0)
```

All 119 captured Pia datagrams decrypted successfully: 116 inbound and 3 outbound. Inbound
protocol messages were Net 1, Session 6, RTT 31, and Reliable 78. The Reliable stream was one
FireRed metadata INIT followed by 77 sequential copies of the same `WC` connect request. The
Switch kept advancing from `fff1` while advertising window base `fff0` because the PC sent no
Reliable acknowledgement.

The same UI message therefore has a new, later cause. The CCMP/ARP and Pia Session work is
complete. The next implementation is the host/parent Reliable bootstrap from the native gold:

1. ACK guest INIT `fff0` with next-expected `fff1`;
2. receive the first `WC` connect request;
3. send native host `WA` accept with host INIT framing and cumulative ACK;
4. continue host-side Reliable/RFU/NI processing before releasing the game engine.

A secondary teardown issue remains: interrupting HostTransport after the peer left did not
unwind the radio thread within its 15-second grace. The selector safely removed the stale AP,
and both cards passed post-test actual-RX health, but graceful host shutdown still needs repair
before production.
