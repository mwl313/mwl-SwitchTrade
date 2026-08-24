# 43 — Full animation live PASS; finish commit implemented (2026-08-24)

## Outcome

Emulator commit `2d66c08` passed the complete confirmation, `START_TRADE`, scene-seam standby, and
trade-animation path on a real Switch. The user saw the full animation and the message
`Take good care of SALAMENCE`.

The host stopped before player zero sent `CONFIRM_FINISH_TRADE`. On returning to neutral, the
Switch restored the user's original Rattata. This is decisive behavioral evidence that the visible
animation and local party swap are provisional until the source-defined leader finish transaction.

Commit `812fb90` implements that exact next transaction. It is offline-test-proven and deliberately
has not been hardware-tested while the user is away.

## Live evidence

Capture: `logs/golden/pc_host_start_trade_live_20260824_191729/`

| Host time | Event |
|---:|---|
| 119.2 s | child `READY_TO_TRADE cursor=1` |
| 119.2 s | parent `SET_MONS_TO_TRADE`, local cursor 1 / child cursor 1 |
| 119.5 s | parent `INIT_BLOCK` started |
| 119.6 s | parent `INIT_BLOCK` complete |
| 125.5 s | child `INIT_BLOCK` complete |
| 125.5 s | parent `START_TRADE` |
| 125.6 s | scene-seam standby count 4 initiated |
| 126.5 s | standby count 4 complete |
| 157.7 s | child `READY_FINISH_TRADE` |
| visible | animation completed; `Take good care of SALAMENCE` |
| after stop | neutral-state rollback restored Rattata |

No `received.pk3` was produced because the commit transaction had not occurred.

## Capture integrity

```text
Pia authenticated       7,333 / 7,333
Pia failures            0
direction               3,412 out / 3,921 in
host monitor            18,694 captured / 18,707 filter / 0 kernel drops
host TAP                 7,439 captured / 7,439 filter / 0 kernel drops
RTL8188EU observer       18,823 captured / 18,838 filter / 0 kernel drops
post-test radio health  PASS / PASS, restored to channel 6
```

Joined-session teardown again exceeded the 15-second radio-thread grace. The process exited, the
selector removed only the exact stale AP, retained/reused the monitor, and both actual-RX health
gates passed. This remains a cleanup defect, not an RF receive failure.

| File | Bytes | SHA-256 |
|---|---:|---|
| `host_console.log` | 16,370 | `9329ca52c1b6fc6df6cd4d89480b48db3688bb4dc29d7c3bbeb3c8e7dc114c8a` |
| `host_ldn_mon.pcap` | 4,601,003 | `5a2ee9062bed1aafa0d1a20c6ac1aa7c6ac765c9c1bde7e6d708b52ed2106ea5` |
| `host_ldn_tap.pcap` | 1,113,021 | `ad9e9ee3c469593e766e643f98123c1854a58749c7e3d6f73d6dfc058538ce34` |
| `observer_rtl8188_ch6.pcap` | 3,915,442 | `7547f5adb124193896da29601544b6f5305905330286bbe659d74a4ef05a3c43` |
| `pc_host_pia.jsonl` | 2,512,119 | `830612dfc8602aaf0855ababa1f9b799b6a92b6aff83ae88cba31a4dab1a0bea` |

The capture-local `MANIFEST.md` also locks the runner scripts and exact launch build.

## Source-defined finish transaction

`pret/pokefirered` `trade_scene.c` requires:

1. Each player sends `LINKCMD_READY_FINISH_TRADE` after `DoTradeAnim` / `TradeMons`.
2. Player zero waits until its local status and the partner status are both READY.
3. Player zero broadcasts `LINKCMD_CONFIRM_FINISH_TRADE`.
4. Receiving row-zero CONFIRM advances into evolution/save/return processing.

The live rollback independently validates that this is a real commit boundary, not cosmetic traffic.

## Implementation in `812fb90`

- Parent mode separately tracks local and child `READY_FINISH_TRADE` completion.
- The existing local engine emits the owner-zero READY block after animation.
- Child READY cannot arm the gate before `START_TRADE`.
- Only when both READY blocks are complete and no sender is active does player zero transmit an
  owner-zero `CONFIRM_FINISH_TRADE`.
- The local engine commits at the same boundary and enters its existing save/return state.
- A focused wire test proves owner zero on local READY and CONFIRM, the two-sided gate, one local
  commit, and entry into the leaving sequence.

Verification:

```text
WSL ordinary emulator tests       136/136 PASS
Windows relay integration tests      4/4 PASS
Functional total                   140 PASS
```

The complete Windows discovery run has six unrelated `test_detect_phy` setup errors because Windows
cannot create the Linux sysfs symlink fixture; those tests pass under WSL. WSL discovery still has
only the known missing-`uvicorn` relay setup error, and the four relay tests pass in Windows.

## Restart point after the pause

Do not start another live run until the user returns. Then run the standard dual-radio health-gated
capture and repeat join, sit, select, Trade, Yes. The next PASS is:

```text
local READY_FINISH_TRADE complete
child READY_FINISH_TRADE complete
parent CONFIRM_FINISH_TRADE
Switch proceeds into save/return
trade remains committed after neutral state
```

Do not claim full graceful completion yet. The next likely unproven leader responsibility is the
save/return/menu-reentry path, including any player-zero barrier, party repull, or cancel/leave
transition that appears after CONFIRM. Let the next capture identify that exact boundary.
