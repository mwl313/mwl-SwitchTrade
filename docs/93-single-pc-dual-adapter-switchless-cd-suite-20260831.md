# Single-PC dual-adapter, Switchless C+D qualification suite

Status: qualification campaign closed after Q0-Q5 and the user-approved Q6 source/runtime 10/10;
production packaging is intentionally not required, 2026-08-31

Q0 now defines the versioned redacted report/state contract, immutable advertisement fixture
identity, unpredictable challenge evidence, strict transition model, and pure validation tests. Q1
extends the existing production `UsbLease` with an optional exact Linux sysfs identity while keeping
the default single-adapter public evidence and private recovery record unchanged. Two identical
`0bda:818b` fakes now prove independent attach, probe, crash recovery, reverse release, and one
attach/detach per exact Windows identity. The latest full qualified Python regression is `567 passed, 3
skipped`. Q2 adds two canonical isolated worker processes with private configs, identity-bound file
control, mutation-free status projection, the real hosted C0/C1/C2 path, and authority D. Hosted run
`q2-normal-20260831-04` passed through `C_SYNTHETIC_RFU_PROVEN`, verified the delayed one-sided
barrier, terminalized the no-trade authority attempt as canceled, and removed the room, credentials,
and workers. `q2-worker-death-20260831-01` preserved `CD_WORKER_EXITED` and also verified cleanup.
No Q0-Q2 run attached USB, invoked WSL radio preparation, or touched a Switch. Q3 then proved two
exact attach-delta identities, distinct PHY/netdev ownership, actual RX, and reverse cleanup in
`q3-radio-20260831-03`. Q4 `q4-integrated-20260831-01` held both exact leases while the real hosted
relay passed C0/C1, delayed C2 activation, bidirectional synthetic RFU, authority D, and all cleanup.
Q5 passed 125 focused identity/order/C/D fault tests plus a real-relay worker-death expected failure.
Q6 passed 10/10 valid integrated cycles with no forced worker, room, credential, recovery, Linux USB,
or Windows USB ownership residue. The user reduced the repetition target from 30 to 10 during the
campaign. These runs used the installed immutable WSL runtime with the current source-qualified Q3/Q4
orchestrator. Their purpose was to qualify the remaining C+D and exact-resource boundaries before
product wrapping, not to create a dual-radio product mode or a separately shipped test application.

This document defines a focused qualification campaign for the remaining software C and distributed
D boundaries. It follows the normative
[ABC+D architecture](80-abc-connection-architecture-20260829.md), does not supersede it, and must be
implemented with the recurrence-prevention rules in
[Mistakes to Avoid](MISTAKES_TO_AVOID.md).

The suite uses one Windows PC, one installed SwitchTrade WSL runtime, two distinct supported USB
radios, two isolated logical side workers, and the real hosted relay. It uses no Switch console and
does not depend on the retiring desktop GUI.

## 1. Decision and current discovery result

The newly connected radio is detected correctly. The current installed control inventory and
Windows USB/IP inventory agree that:

- two distinct RTL8192EU `0bda:818b` devices are present;
- both match the existing `beta-candidate` hardware profile and are selectable;
- both are currently Windows-owned and unattached to WSL;
- the previously used device remains USB/IP-authorized;
- the newly connected device was explicitly authorized by exact Windows InstanceId for Q3-Q6;
- both devices were restored to Windows ownership after the campaign.

Detection and active dual-radio qualification pass. The two-lease owner and entry point remain
qualification-only source tools. They are not required in the production package because the shipped
product owns one selected radio per PC. The initial discovery performed no selection, share, attach,
detach, or repository mutation; the later Q3-Q6 campaign explicitly authorized the second adapter and
performed the bounded ownership transitions recorded above.

The private run state may retain exact Windows InstanceIds for recovery. Repository documents,
support reports, and logs retain only redacted hashes and never record MAC addresses or the operator's
profile path.

## 2. Exact scope

The suite answers one question:

> Can two isolated local sides on one installed PC hold two exact radios, create one authoritative
> attempt through the real relay, prove the non-physical C data path, and complete distributed D with
> both radios and all shared resources returned correctly?

It is named `single-pc-dual-adapter-cd.v1`.

It may prove:

- two distinct adapter identities can be acquired concurrently without cross-binding;
- both radios can remain P0-ready for the lifetime of one shared attempt;
- C0 room membership, distinct credentials, complementary roles, attempt lock, launch identity,
  authenticated WebSockets, ordered peer readiness, and an unpredictable two-way nonce;
- C1 ordered delivery of one immutable package-owned advertisement fixture;
- C2 current-generation side-ready barriers, bounded pre-barrier traffic, ordered synthetic RFU
  boundary payloads, reconnect re-proof, and stale/replay rejection;
- D1-D11 normal, canceled, failed, and recovered cleanup with two local resource owners;
- one attach and one prior-state restoration per run-acquired adapter, with zero orphan process,
  room, credential, interface, PHY, lock, or recovery state.

It cannot prove:

- A room scan, advertisement parsing, station association, CCMP key installation, or Nintendo control
  port against a real Switch;
- B over-air advertisement, Switch association, participant count, or Nintendo control port;
- real RFU traffic from either Switch, a trade, save, menu return, or link-close tail;
- two independent Windows kernels, WSL VMs, clocks, schedulers, NATs, power states, or failure domains;
- simultaneous physical `A_READY` and `B_READY`, because no physical A or B transport runs.

A pass is a focused C+D and dual-resource qualification result, not a full ABC+D certificate and not
a replacement for the final two-PC/two-Switch campaign.

## 3. Tests excluded from this campaign

The following are excluded from the installed runtime campaign, not deleted from source control:

1. P0 cold-boot qualification already accepted on both PCs.
2. Direct A A0-A9 qualification already accepted on both PCs.
3. Direct B B2-B10 qualification already accepted on both PCs.
4. Previously passed standalone C0/C1/C2 unit, property, and relay smoke matrices.
5. Installer, desktop UI, and legacy production-diagnostics tests unrelated to this boundary.
6. Every Switch-dependent A, B, physical C2, trade, save, and close-link case.

The existing regression tests remain in CI because removing them would remove protection from the
production components. They are merely absent from this focused installed campaign and its pass
count.

P0 safety checks are not removable. Each live run must minimally prove the exact release, runtime,
adapter ownership, driver/firmware, PHY/netdev, required crypto/TUN modules, and actual RX for each
selected radio. These are run prerequisites and cleanup authority, not repeated A/B qualification
claims.

## 4. Architecture

```text
Switchless C+D coordinator (one owner of the campaign)
  ├─ logical room-side worker
  │    ├─ exact adapter lease A
  │    ├─ isolated state root / launch identity / relay member token
  │    └─ package-owned diagnostic boundary (no Direct A transport)
  ├─ logical AP-side worker
  │    ├─ exact adapter lease B
  │    ├─ isolated state root / launch identity / relay member token
  │    └─ package-owned diagnostic boundary (no Direct B transport)
  └─ one real private relay room
       ├─ two distinct credentials and stable seats
       ├─ one complementary-role locked attempt
       ├─ C0/C1/C2 production contracts
       └─ D1/D6 authority barrier and retirement
```

The coordinator is a GUI-independent qualification command. It does not start two desktop apps or
two copies of the current control service. Two desktop copies would conflict on the desktop mutex,
control port, state root, scalar hardware owner, and process-wide lock.

The two side workers are separate processes so process death, timeout, and recovery are real
boundaries. They reuse the production `P0Harness`, hardware profile, relay client, `CStage`,
`C2Bridge`, `EndpointDStage`, measured D control, and D7 resource cleanup. The package-owned
diagnostic boundary supplies only the missing physical A/B result:

- a release-hashed, immutable FRLG advertisement fixture for C1;
- unpredictable per-run nonce challenges and bounded synthetic RFU application payloads for C2;
- current attempt/seat/role/run/generation evidence for side-ready messages.

It never imports or launches `DirectAHarness`, `DirectBHarness`, `LiveTransport`, or `HostTransport`,
and it cannot be selected by a normal trade room.

## 5. Dual-adapter identity and ownership contract

Both physical devices currently share the same VID:PID, so `0bda:818b` is a hardware profile, not a
device identity. The existing Linux probe and scalar control owner are insufficient for a dual-radio
run. Implementation must first introduce a reusable exact-device lease with no behavior change to
the normal single-radio path.

### 5.1 Identity

Each side binds all of the following:

- stable Windows InstanceId;
- current USB/IP bus ID, resolved immediately before each ownership mutation;
- supported hardware profile and allowed driver;
- run-local Linux USB sysfs path discovered by an attach delta;
- the exact run-local driver, PHY, and netdev descendants;
- lease ID, run ID, launch generation, and owner PID/start identity;
- prior Windows/WSL ownership state.

The public report stores only hashes of stable physical identities. A bus ID is transient and cannot
replace InstanceId. VID:PID alone can never select, probe, detach, or clean one of two identical
radios.

### 5.2 Ordered acquisition

1. Prove exactly two distinct requested InstanceIds resolve once and are both authorized,
   Windows-owned, unattached, and compatible with the installed hardware profile.
2. Acquire one suite lock plus two per-device cross-process locks in deterministic identity-hash
   order. A normal room, diagnostic, or unresolved recovery guard blocks the suite.
3. Resolve adapter A's current bus ID and attach only A.
4. Compare Linux USB sysfs snapshots and require exactly one new matching device. Bind its sysfs
   identity and descendants to lease A; ambiguity is a hard failure.
5. Complete A's minimal P0b driver/module/TUN/PHY/netdev/RX gate and retain the lease.
6. Repeat the attach-delta and P0b sequence for adapter B while A remains attached and unchanged.
7. Prove the two leases own different USB devices, PHYs, netdev sets, locks, and recovery records.
8. Publish two `P0_SIDE_READY` attestations only after both mappings remain stable.

If Linux serial data is present it is supporting evidence, not the only mapping authority. Missing,
duplicated, changing, or contradictory identity fails closed. No fallback assigns devices by
enumeration order.

### 5.3 Ordered release

Each worker stops its own endpoint and proves its own interfaces and PHY quiescent. The coordinator
then restores adapters in reverse acquisition order, resolving current bus identity from the stable
Windows InstanceId immediately before detach. A lease that did not attach a device never detaches it.
The suite becomes terminal only after both exact Linux devices disappear for a bounded stable
interval and both adapters match their prior Windows ownership state.

## 6. Suite cases

### 6.1 CD-NORMAL — integrated C0/C1/C2 to D11

1. Run passive release/runtime/relay/exclusivity checks without changing USB ownership.
2. Create one private room; join once with a second distinct member; verify unique credentials,
   stable seats, current versions, and complementary logical roles.
3. Acquire both exact radio leases in the ordered sequence above and keep them until D.
4. Publish two distinct P0 attestations and lock one authoritative attempt.
5. Launch one identity-bound worker per side and validate run ID, attempt ID, seat, role, generation,
   nonce, PID, adapter lease, and PHY.
6. Authenticate both WebSockets; prove ordered `PEER_READY` and unpredictable two-way C0 nonce.
7. Send the immutable advertisement fixture from the logical room side; verify attempt, epoch,
   sequence, size, and hash on the logical AP side.
8. Arm both C2 bridges, deliberately delay one side-ready signal, and prove no early activation and a
   bounded pre-barrier queue.
9. Complete the same-generation side-ready barrier and exchange unpredictable bidirectional
   synthetic RFU boundary payloads with ordered hashes and counters.
10. Enter D with a normal diagnostic-complete outcome. Complete D1-D6, close suite-owned D7 room and
    credential resources, prove D8-D10 independently for both sides, and release all locks at D11.

### 6.2 CD-IDENTITY-ORDER — fail-closed contract cases

Run one focused case for each new dual-owner boundary:

- duplicate InstanceId selection;
- same VID:PID with swapped or stale bus IDs;
- a missing second authorization;
- ambiguous or missing Linux attach delta;
- cross-bound PHY/netdev evidence;
- duplicated member credential or non-complementary role;
- stale attempt, epoch, launch acknowledgement, side-ready generation, nonce, or advertisement;
- duplicate, gap, wrong-direction, oversized, and pre-barrier-overflow frames;
- repeated read-only status polling, which must produce zero launch, attach, readiness, or cleanup
  mutation.

Every case stops before the next unsafe mutation, preserves the first factual failure, and either
proves zero ownership was acquired or completes exact recovery.

### 6.3 D-FAULT-RECOVERY — two-owner lifecycle matrix

Exercise cancellation or failure at these boundaries:

- before either attach;
- after adapter A attaches but before adapter B attaches;
- after both P0 sides are ready;
- during attempt lock and each worker launch;
- during C0 nonce, C1 advertisement, pre-barrier C2, and active synthetic C2;
- during D1, endpoint drain, side-quiescent acknowledgement, two-side terminal barrier, first
  adapter return, and second adapter return;
- one worker's graceful exit, early exit, and controlled crash;
- one WebSocket disconnect and reconnect generation, without restarting or mutating the hosted relay;
- application/coordinator restart with an exact private recovery record;
- injected `present`, `absent`, and `unknown` cleanup-probe results at deterministic seams.

The primary C or process failure is never overwritten by later `peer_lost`, cancellation, or cleanup
failure. Any unknown cleanup evidence leaves the recovery guard and blocks another run.

## 7. State and report contracts

One parent campaign record owns two immutable side records. Its minimum state machine is:

```text
created
  -> passive_preflight
  -> acquiring_a
  -> acquiring_b
  -> p0_ready
  -> authority_locked
  -> c0
  -> c1
  -> c2
  -> closing
  -> cleaning_b
  -> cleaning_a
  -> terminal
```

Cancellation only requests a transition; the coordinator remains the sole cleanup owner. A process
restart resumes from the persisted owner and lease identities. Status reads are projection-only.

The redacted `single-pc-dual-adapter-cd-report.json` contains:

- suite/release/runtime/fixture/relay contract and source hashes;
- run, room-hash, attempt, role, seat, epoch, and generation evidence;
- per-side gate outcomes, monotonic timings, PID identity proof, and adapter-identity hash;
- nonce and frame payload hashes, sizes, counts, ordering, queue depth, and reconnect generation;
- first failure, secondary failures, last passed gate, cancellation origin, and recovery outcome;
- Boolean D1-D11 evidence for each side and shared authority cleanup;
- proof that the final state equals each adapter's recorded prior ownership state.

It never contains member credentials, room passcodes, raw frames or captures, MAC addresses,
trainer/Pokémon data, exact Windows InstanceIds, or operator paths. Exact recovery identities live in
a separate private local record and are deleted only after verified D11.

## 8. Acceptance

An individual normal run passes only when:

- both sides agree on release, test/run ID, room, attempt, seats, complementary roles, epochs, and
  activation generation;
- both exact adapter leases remain distinct and stable from P0 through D;
- C0 two-way unpredictable nonce, C1 fixture hash, C2 side-ready barrier, and bidirectional synthetic
  payload hashes pass;
- both endpoint processes and all children exit;
- the temporary room, both credentials, attempt, retained frames, and WebSockets are retired;
- no matching interface, PHY activity, lock, token, session, or recovery guard remains;
- both adapters are restored exactly once to their initial Windows-owned, unattached state;
- repeated read-only status calls caused no mutation.

The completed focused qualification target was:

- one fast normal run plus the focused new identity/cancellation cases during development;
- 10 consecutive `CD-NORMAL` runs, as explicitly approved for this campaign;
- one pass of every `CD-IDENTITY-ORDER` and `D-FAULT-RECOVERY` case;
- zero unresolved cleanup, duplicate launch, cross-bound adapter, orphan authority, or warning storm.

The 10/10 result closes this focused campaign. It does not authorize a full product release and does
not replace the later packaged normal-application and two-PC/two-Switch gates.

## 9. Confirmable implementation milestones

This work must not be implemented as one large change.

1. **Q0 — Contract and fixtures:** add schemas, immutable fixture hash, state/result types, and pure
   validation tests. No WSL, USB, relay mutation, or normal-path edit.
2. **Q1 — Exact-device lease primitive:** refactor the current scalar hardware owner into a reusable
   exact-device lease while preserving the normal one-adapter public behavior byte-for-byte. Prove
   current P0, normal room, diagnostic, cancellation, and recovery regression before continuing.
3. **Q2 — Two software side workers:** run C0/C1/C2 and authority D with two isolated local workers,
   separate state roots, one real room, and no radios. Prove process death and status immutability.
4. **Q3 — Dual-radio ownership:** add deterministic two-lock acquisition, attach-delta mapping,
   per-PHY P0 evidence, reverse cleanup, and restart recovery. Test with fakes first, then one bounded
   installed acquisition/cleanup run without C.
5. **Q4 — Integrated normal case:** combine Q2 and Q3 and pass one `CD-NORMAL` installed run. Stop and
   fix any ownership ambiguity before fault injection.
6. **Q5 — New fault matrix:** implement only the dual-owner and composed-boundary cases listed above;
   retain all original failures and prove cleanup after each.
7. **Q6 — Source/runtime qualification:** run 10 consecutive normal cycles and every focused fault
   case, review redaction and residue, then record the evidence boundary.

No milestone changes the old GUI. No suite result authorizes deleting the existing A/B regressions or
skipping the later physical two-PC/two-Switch test.

## 10. Handoff to production work

Q3-Q5 and the user-approved 10-cycle Q6 source/runtime campaign pass, so additional dual-adapter
testing stops here. Do not spend the next product milestone packaging this qualification entry point.
The next work is the deterministic one-radio production wrapper in
[the beta cutover decision](94-production-wrapper-beta-cutover-20260831.md), followed by its minimal
GUI, support-log export, immutable package, and final two-PC/two-Switch acceptance. Switchless
synthetic RFU evidence never replaces that final physical test.
