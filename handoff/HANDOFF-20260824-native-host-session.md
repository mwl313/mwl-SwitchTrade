# Handoff — native host Session gold and next gate (2026-08-24)

## Read first

The authoritative analysis is `docs/30-native-fixed-handshake-20260824.md`. The raw pcaps
are local, immutable test evidence under `logs/golden/native_fixed_handshake_20260824_live/`
and are intentionally ignored by Git. Verify their SHA-256 values against that document
before re-analysis.

## Current state

- Main repository: branch `golden-capture-re`.
- Emulator repository (`emu/`): branch `gptsolreview`, fix commit `be18d57`.
- Native two-Switch room creation, join, trading-room entry, idle period, and graceful exit
  were captured on channel 1 by both WSL radios with zero kernel drops.
- RTL8192EU gold: 18,252 decrypted Pia datagrams, zero Pia authentication failures.
- The missing PC-host protocol bytes are no longer unknown.

## Root cause fixed

The PC host announced an empty Net `0x11` station table and stopped before accepting the
guest Session. A native host sends six NetStation records, Session type `2`, and Session type
`5`; the guest then finalizes with type `6`.

The emulator branch now reproduces those native payloads and their Pia framing. Five focused
tests lock the Net table, constant-ID permutation, join parser, Session payloads, compression,
header destination/source IDs, per-channel packet IDs, and recipient footer.

## Deliberate safety gate

Do not change `HostConnectionManager.connected` to true yet. `pia_connected` becomes true
after Session type `6`, but the existing `Sim._drive_reliable()` is the guest/child role. If
released in host mode it would send child metadata and a child `WC` request when the PC must
instead acknowledge the Switch's metadata and answer its `WC` with host `WA`.

## Immediate next test

Run a one-Switch WSL PC-host smoke test with the health gate in front of both host and observer
captures. Ask the user only to remain on the join-room screen, select the PC room when told,
and report the exact UI result.

Required wire milestones:

```text
PC -> broadcast  Net 0x11 (size 0x84, six station records)
Switch -> PC      Net 0x12
Switch -> PC      Session 0
PC -> Switch      Session 2
PC -> broadcast   Session 5
Switch -> PC      Session 6
Switch -> PC      Reliable INIT, FireRed metadata
```

Stop and preserve the capture after the first Reliable INIT. If Session `6` or Reliable INIT
is absent, compare the exact outgoing type `2`/`5` framing before modifying any game logic.

## Next code step after that gate passes

Add a separate host/parent Reliable bootstrap rather than branching the child logic invisibly:

1. receive guest INIT (`flagsA=0x0f`, sequence `fff0`) and send cumulative bulk ACK `fff1`;
2. receive guest emulator `WC` connect;
3. send host INIT `WA` accept and the cumulative ACK;
4. implement the parent slot/NI direction using the native capture as the fixture;
5. release the trading engine only after the host RFU link has accepted the child.

The native first Reliable sequence is recorded in section “Remaining roadblock” of doc 30.

## Verification baseline

```text
python -m py_compile frlgsim/pia_connect.py frlgtrade.py tests/test_pia_host.py
python -m unittest tests.test_pia_host -v       # 5/5 PASS
python -m unittest discover -s tests -p 'test_*.py' -v
```

The full discovery currently has 123 ordinary passes and one pre-existing environment error:
the optional relay offline suite cannot import `uvicorn` from this venv. Do not misclassify it
as a Pia regression.

## System constraints that remain valid

- RTL8192EU is the project host card.
- Patched RTL8188EU is viable for monitor capture and guest/relay use but remains blocked from
  project host mode because AP+monitor deadlocks in the vendor cfg80211 driver.
- Always use `scripts/radio-health-gate.sh` before capture. A card being present in `iw` is not
  proof that receive is alive.
- Do not commit `prod.keys`, derived permanent console secrets, or raw pcaps.
