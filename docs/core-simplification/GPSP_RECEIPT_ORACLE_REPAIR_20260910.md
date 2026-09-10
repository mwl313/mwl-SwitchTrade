# Stock gpSP qualification: independently paced receipts and game data

Branch: `codex/gpsp-endpoint`. Local and actual remote baseline:
`42f973427b8adc29e60fa3bf5f0012dcd8902a2d`.
Scope: unattended qualification repair. No product protocol/timing change,
physical Switch/VM/radio operation, installation, deployment or user game access.

## First failure and verified cause

CI run [34396624238](https://github.com/mwl313/mwl-SwitchTrade/actions/runs/34396624238)
failed in both Windows full-stack probes; Ubuntu passed. The oracle expected
WK immediately after each parent WT, but the next homebrew WT arrived first.
The endpoint's previously committed receipt cadence makes these independent:
the homebrew can consume parent data and reply before the local receipt flush.
Core/Reliable ordering is not violated: that is the endpoint's admission order.

`FullStackProbe` now requires exactly one correlated WK and one next WT, in
either order. It retains at most one early packet, never scans past or discards
unexpected traffic. Each test parent has one outstanding response; exact WK
size, sequence, mask and timestamp are verified. Exact WT length, header,
slot layout, nonzero timestamp and homebrew round/counter/payload are checked.
Duplicate/missing packets, wrong flags and disconnect still fail the probe.
No synthetic acknowledgement, extra sleep or larger production queue is added.

Each round reports `receipt_verified_exchanges` and `data_before_receipt`.
The attestor requires verified receipts to equal completed bidirectional
exchanges and checks the order count's range. Neither prefix matching alone
nor a missing receipt can establish completed qualification.

## Verification ledger

- Windows Python 3.12.14 and 3.14.7: 46 oracle/attestation checks pass each.
  These are modeled validator tests, not real-process evidence.
- Fresh final-source Python 3.12 selection: 125 cadence/converter/endpoint/
  actual-relay/LDN pressure-path/oracle/attestation checks passed in 88.99 s;
  five agent-context policy checks passed separately. Existing dependency
  deprecation warnings remain. No required physical test was skipped into PASS.
- Two short real-stock runs used the existing checksum-pinned runtime, copied
  into fresh isolated test directories. The final instrumented run completed
  28 exchanges in round one and 8 in round two, with exactly 28 and 8 matching
  receipts. Data preceded its receipt 27 and 7 times respectively. Both rounds
  used the same Pair, Netplay connection and running homebrew process.
- Short-run cleanup: native CLI normal stop, test-owned frontend exit zero,
  sockets/handles/private desktop closed, virtual OS resources clean, and
  original stock runtime tree unchanged. No real console or commercial game
  was involved. Raw local reports remain under ignored `.qualification/`.
- Short runs used an uncommitted repair and shortened waits/traffic durations.
  They are not final-SHA or 30-minute qualification. Final committed runs and
  exact-SHA Windows/Ubuntu CI must establish those separate gates.
- An overlapping development test run collected the old test fixture before
  receipt counters were added, then imported the changed oracle later: nine
  AttributeErrors, not a pass. It completed and was superseded by a fresh
  source-stable run. A bare 3.14 interpreter lacked pytest; the existing 3.14
  test environment was used instead, without installing dependencies.

## Completion and physical handoff

Final source identity is the commit containing this record. Only generated
`GPSP_ACCEPTANCE.final.json` / `ABC_SOFTWARE_PREFLIGHT_CLOSURE.final.json`
artifacts after successful exact-SHA jobs attest their respective software
scope. Do not treat this checked-in narrative as an independently completed CI
or actual-process soak. The previous cadence repair and its physical limitations
remain in `GPSP_JOIN_CADENCE_REPAIR_20260910.md`.

After software verification, the next separately authorized physical trial
must use updated Host and VM checkouts, a fresh Pair and fresh log directories.
Keep the existing supported stock core and manual Netplay/game workflow; no
relay deployment or reinstall is needed for this test-only repair.
Verify native END_ACK -> NULL -> parent NI -> UNI -> actual room entry -> party
selection -> completed trade, then clean room exit and a second Generation.
`Bridge active` and successful homebrew traffic do not prove Pokemon trade/save
completion. If unavailable recurs, retain both full logs through cleanup and
identify the first missing game milestone rather than blindly retrying.

ESP32, other emulator adapters, battle and RSE work are deliberately unchanged.
