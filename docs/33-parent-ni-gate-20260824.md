# 33 — Live parent WA proof and parent NI gate (2026-08-24)

## Outcome

The one-Switch PC-host run crossed the parent Reliable gate.  The Switch ACKed
the PC's native `WA` accept with zero Pia decrypt failures, then immediately
started the child RFU NI transfer.  The screen still showed “Awaiting CODEX's
response” followed by “The other Trainer appears unavailable” because the old
build supplied only Pia Reliable ACKs and never answered that RFU NI transfer.

This is a later boundary than every previous identical-looking UI failure.
Beacon discovery, association, ARP, Pia Net/Session, Reliable `WC/WA`, and the
Switch's acceptance of the parent link are now proven on real hardware.

Emulator branch `gptsolreview`, commit `c69e213`, implements the capture-locked
parent poll and bidirectional NI join-status exchange.  Parent UNI/player-zero
polling remains the next room-entry gate.

## Live evidence

Local, ignored evidence directory:

`logs/golden/pc_host_parent_wa_live_20260824_151803/`

| File | Bytes | SHA-256 |
|---|---:|---|
| `host_ldn_mon.pcap` | 623,323 | `fd195f916fed029985dbb29b8348ad12612c6d5815954bdb69935f1e3eee9348` |
| `host_ldn_tap.pcap` | 10,925 | `1873a0c0de0fcabfdfbec6234bd3bd10a3444bce9cdf5bac0b5de61d4de0ab95` |
| `observer_rtl8188_ch6.pcap` | 760,390 | `28f10cbf7cde4ae4d47bb8d1e76165579321628ec6efb8dbd6b40f0235c296ee` |
| `pc_host_pia.jsonl` | 23,922 | `6cfe4f77f1fd4c8cb66a26ee730151494b958cc247b7845f69b69be161bce144` |

Both captures had zero kernel drops.  Both radios passed actual-RX health gates
before and after the test and were restored to channel 6.

```text
channel/BSSID       6 / a0:47:d7:b0:2b:39
Switch              98:41:5c:79:41:38
subnet              169.254.20.0/24 (PC .1, Switch .2)
PC RFU session id   0x1b3f (wire 3f1b)
Switch WC id        2b51
Switch Pia var      0x0790
Pia JSON records    79
Pia decrypt failures 0
```

The decisive live sequence was:

```text
Switch INIT fff0
Switch WC fff1                    574302002b51
PC WA fff0                        574106003f1b2b510000
PC cumulative ACK fff2
Switch cumulative ACK fff1
parent_link_accepted=True
```

After that ACK, the Switch sent 17 child `T` frames at Reliable sequences
`fff2..0002`, approximately every 340 ms.  Every frame carried the same RFU
NI_START semantics:

```text
child LLSF     state=NI_START ack=0 n=1 phase=0 size=7
NI header      data_type=1 payload_size=12 data_size=26
first slot     8704010c001a000000000000
```

The PC returned cumulative Pia ACKs through `0003`, but no parent `T` frame.
The Switch therefore had transport delivery without an RFU-layer response and
eventually disconnected with `WD`.

## Native post-WA truth

The same boundary was decoded from the native CH1 two-Switch gold:

`logs/golden/native_fixed_handshake_20260824_live/fixed_ch1_rtl8192.pcap`

Offline quality was 18,257/18,257 protected Wi-Fi frames decrypted and
18,252/18,252 Pia datagrams authenticated, with zero failures.

| Native frame | After `WC` | Host action | Essential payload |
|---:|---:|---|---|
| 1282 | 0.265 s | first parent idle poll | `57540800...01000000` |
| 1289 | 0.296 s | ACK child NI_START | parent LLSF `006804` |
| 1291–1303 | 0.315–0.396 s | ACK child NI data/end | `00a804`, `00aa04`, `00ac04`, `00e004` |
| 1318 | 0.483 s | child-NI boundary | `5747040000000000` (`WG=0`) |
| 1644–1665 | 5.398–5.529 s | parent join-status NI | five frames, status `05` |
| 1700 | 6.030 s | parent-NI boundary | `5747040001000000` (`WG=1`) |
| 1745 | 6.731 s | first parent UNI poll | 73-byte parent slot, LLSF `460005` |

The five parent NI slots are byte-locked in tests.  They carry a seven-byte NI
header split across two five-byte parent payload windows, one status byte
`JOIN_GROUP_OK=5`, NI_END, and NULL.  The parent advances only after the child
returns a matching RFU ACK for each non-NULL subframe.

## Implemented boundary

Commit `c69e213` adds only the parent-role pieces demonstrated above:

- parent-format `T` builder, including the native idle encoding;
- three-byte parent LLSF encode/decode;
- child NI receive ACKs;
- exact parent `JOIN_GROUP_OK` NI slots;
- matching-ACK-driven parent NI advancement;
- `WG=0`, `WG=1`, and periodic parent idle polls;
- a separate `parent_ni_complete` milestone.

The existing child/right-seat `TradeEngine` remains gated.  It asserts player
one and emits child LLSFs, so reusing it in host mode would reverse the RFU
roles.  The next implementation must create parent UNI frames for player zero,
reflect the joined child's command row, and reproduce the native
`SEND_PLAYER_IDS`/LinkPlayer block bootstrap.

## Verification

```text
py_compile relevant modules                  PASS
tests.test_pia_host                          8/8 PASS
ordinary emulator tests                     131/131 PASS
full discovery relay integration            setup error: uvicorn absent in this venv
```

The relay setup error is environmental and unrelated to parent RFU/NI; it
occurs before that test class runs.

## Joined-session teardown correction

The earlier local-self-DESTROY adapter remains a valid fix for a no-peer room:
real stop completed in 1.191 seconds.  It is not a complete joined-session fix.
After this live run, Ctrl-C again reported:

```text
RuntimeError: host radio thread still alive - refusing concurrent vif cleanup after 15s
```

The process then exited, the selector removed the stale AP, and both cards
passed post-test RX.  The remaining hang is likely later in the ldn AP context
exit after a station has associated; capture a thread stack on the next
reproduction before changing cleanup again.

## Next gate

Do not repeat the old WA-only build.  The next one-Switch test must use
`c69e213` and stop after one of these outcomes:

1. `parent_ni_complete=True` and the Switch begins child UNI traffic — NI gate
   passed; implement parent UNI/player-zero bootstrap.
2. The child repeats one NI subframe — compare the repeated `(state,n,phase)`
   against the matching PC parent ACK.
3. The Switch disconnects before child NI — regress WA/transport first.

Entering and holding the trading room remains one known protocol gate beyond
NI: parent UNI plus the player/link-block bootstrap.
