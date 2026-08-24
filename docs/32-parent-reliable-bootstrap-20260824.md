# 32 — PC-host parent Reliable bootstrap and no-peer teardown (2026-08-24)

> Follow-up correction: the live WA gate passed, but joined-session teardown
> still hangs after the 15-second grace.  The parent NI implementation and the
> corrected teardown scope are in `docs/33-parent-ni-gate-20260824.md`.

## Outcome

The next PC-host boundary is implemented on emulator branch `gptsolreview`,
commit `4478ec9`:

- ACK the Switch guest's Reliable INIT at sequence `fff0`;
- parse the first emulator `WC` connect request;
- send the native parent `WA` accept using the RFU session id already advertised
  in the PC room beacon;
- batch the cumulative `fff2` ACK after `WA`, like the native host;
- retransmit `WA` until the Switch acknowledges it;
- keep the child/right-seat trade engine gated until parent RFU/NI exists.

The separate HostTransport no-peer shutdown hang is repaired and validated on
the real RTL8192EU.  This did not fix the later joined-session shutdown path.

## Native evidence

Reference capture:

`logs/golden/native_fixed_handshake_20260824_live/fixed_ch1_rtl8192.pcap`

SHA-256:

`e6df7e03b2d33c11aaec112306f4605706a11afd9fd35fc9dd97ad768257d0b5`

The authorized LDN and Pia decoders recovered this exact opening sequence:

| Frame | Relative time | Direction | Reliable | Inner payload |
|---:|---:|---|---|---|
| 1264 | 0.000000 s | guest → host | INIT `seq=fff0`, window `fff0` | FireRed metadata |
| 1265 | 0.010147 s | host → guest | CTRL, message flags `0x40` | bulk ACK next `fff1` |
| 1266 | 0.015235 s | guest → host | GBA `seq=fff1`, window `fff0` | `574302001a51` (`WC`, id `1a51`) |
| 1269 | 0.045218 s | host → guest | INIT `seq=fff0`, window `fff0` | `57410600fcc31a510000` (`WA`) |
| 1269 | 0.045218 s | host → guest | CTRL, message flags `0x40` | bulk ACK next `fff2` |
| 1271 | 0.065553 s | guest → host | CTRL, window `fff2` | bulk ACK next `fff1` |

The native room advertisement decodes to RFU session id `fcc3`, exactly the
first two bytes in the `WA` body. The host therefore must not mint a second
random id. The remainder of `WA` is the child's `WC` id (`1a51`) plus two zero
bytes.

## Implementation boundary

`Sim` now has an explicit `parent_session_id` path. It is mutually exclusive
with the existing child `connect_id` path. Host mode passes
`HostTransport.rfu_session_id` in little-endian wire order.

The parent path:

1. starts only after `HostConnectionManager.pia_connected`;
2. accounts for inbound guest Reliable data in the existing selective-repeat
   receive window;
3. sends immediate bootstrap ACKs;
4. pins the first `WC` connect id;
5. queues/retransmits `WA` until the guest's cumulative ACK frees it;
6. exposes `parent_link_accepted` only after that ACK.

`HostConnectionManager.connected` remains false. This is intentional: the
existing game engine emits child-format `T`/NI frames and represents player 1,
whereas the PC-created room must emit parent-format polls and represent player
0. Releasing it after `WA` would invert the RFU roles.

Consequently, the next live UI may still end with “trainer unavailable” after
a later delay. Success for this gate is the Switch's bulk ACK of PC `WA`, not
trading-room entry.

## No-peer teardown root cause and partial repair

Kinnay ldn 0.0.17 `APNetwork._destroy_network()` walks every connected
participant and sends a network-destroy control-port frame. That includes
participant zero—the local AP itself. On RTL8192EU/`rtl8xxxu`, the self-addressed
nl80211 request can remain pending, preventing the trio radio thread from
exiting within HostTransport's 15-second grace.

The guarded runtime adapter now skips only the local AP MAC. A still-connected
remote Switch continues to receive the destroy notification. Site-packages is
not modified.

Real health-gated no-peer validation on the RTL8192EU:

```text
room ready             1.403 s
HostTransport.stop     1.191 s
radio thread           None
owned vifs after stop  0
post-stop monitor      recreated by selector
post-stop actual RX    PASS (channel 1), restored to channel 6
```

The later joined WA test still left the radio thread alive after 15 seconds.
Do not generalize this no-peer result to an associated Switch session; see
document 33.

## Verification

```text
parent bootstrap native-byte test        PASS
teardown local/remote participant tests  PASS
focused host/CCMP/teardown tests          12/12 PASS
emulator full suite                       133/133 PASS
main repository suite                     13/13 PASS
```

The previously failing relay integration test now discovers the shared main
repository by locating `relay/server.py` in its parent tree. This supports both
a physical `main/emu` checkout and the current `emu` junction into `_related`.

## Next live gate

Use one Switch on the join-room screen:

1. run both radio health gates;
2. open the PC room on RTL8192EU and capture host monitor, TAP, Pia JSONL, and
   RTL8188EU observer;
3. have the Switch select CODEX;
4. preserve the run once the Switch ACKs `WA` or disconnects;
5. confirm the following exact wire sequence:

```text
Switch INIT fff0
PC ACK fff1
Switch WC
PC WA + ACK fff2
Switch ACK fff1
```

After that gate passes, implement the parent `T`/NI direction from native frame
1282 onward. Do not attempt another full trade before the parent poll and NI
handshake are byte-verified.
