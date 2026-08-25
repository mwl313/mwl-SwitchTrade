# Authoritative Trade Room, control API, and event contract v1 — 2026-08-25

> Status: frozen for private-beta implementation.
> Contract version: `room-control.v1`.
> Scope: two authenticated members, one active connection attempt, local UI/control state, and an
> opaque RFU data path. Public matchmaking remains a labeled Demo Preview for this beta.

This contract replaces the current process-local group counter and the coupling between `host/guest`,
room ownership, tunnel direction, and radio behavior. Existing endpoints may remain during migration,
but new WPF work must target this contract.

## 1. Non-negotiable invariants

1. A Trade Room has exactly two stable seats: `member_a` and `member_b`.
2. Room ownership, stable member/tunnel identity, and per-attempt Switch room role are independent.
3. A room code locates a room; it is not an authentication or reconnect credential.
4. Every accepted mutation is authenticated, idempotent, and increments `room_version` exactly once.
5. The server is authoritative for membership, presence, readiness, creator assignment, attempt phase,
   leave, close, reconnect deadline, and expiration.
6. A local button click is never evidence that the remote member is online, ready, or connected.
7. Exactly one member is the Switch room creator for an attempt. The other is the finder.
8. Creator transfer is allowed only before `role_locked=true`.
9. RFU forwarding remains opaque; lobby authority must not decode game payloads.
10. Trading remains possible when party decoding or optional analytics is unavailable.

## 2. Identifiers and credentials

| Field | Format | Purpose |
|---|---|---|
| `room_id` | UUIDv7 | Stable server identity; never reused |
| `room_code` | 6 uppercase letters/digits | Human locator; private UI may display/copy it |
| `member_id` | UUIDv7 | Stable seat occupant for the room lifetime |
| `subject_id` | Opaque authenticated beta-account ID | External identity; never displayed as a token |
| `attempt_id` | UUIDv7 | One connection attempt inside a room |
| `command_id` | UUIDv7 | Client-generated idempotency key for a mutation |
| `event_id` | UUIDv7 | Unique event identity |
| `member_token` | High-entropy bearer token | Authorizes one member seat; stored outside WPF |
| `reconnect_token` | Rotating high-entropy bearer token | Reclaims the same seat before its deadline |

The authoritative service stores only token hashes. The local WSL control service obtains tokens from
the external beta authentication/bootstrap flow and stores them using the Windows credential boundary.
WPF receives status and user-facing member data, never bearer tokens.

## 3. Authoritative snapshot

Canonical UI snapshot shape:

```json
{
  "contract_version": "room-control.v1",
  "room_id": "0199...",
  "room_version": 18,
  "name": "Kanto evening trades",
  "visibility": "private",
  "room_code": "A7K2Q9",
  "profile": {
    "owner_display_name": "Leaf",
    "game": "FireRed",
    "language": "English"
  },
  "owner_member_id": "0199...",
  "state": "ready_check",
  "created_at": "2026-08-25T12:00:00Z",
  "expires_at": "2026-08-25T18:00:00Z",
  "local_member_id": "0199...",
  "members": [],
  "attempt": null,
  "device_readiness": {},
  "parties": {
    "member_a": {"status": "available", "snapshot_id": "ps_01...", "snapshot_version": 4},
    "member_b": {"status": "unavailable", "snapshot_id": null, "snapshot_version": null}
  },
  "last_event_sequence": 42
}
```

### 3.1 Member

```json
{
  "member_id": "0199...",
  "seat": "member_a",
  "display_name": "Leaf",
  "is_local": true,
  "online_state": "online",
  "ready_state": "ready",
  "compatibility": "compatible",
  "joined_at": "2026-08-25T12:00:00Z",
  "reconnect_deadline": null
}
```

Allowed values:

- `seat`: `member_a`, `member_b`
- `online_state`: `online`, `reconnecting`, `offline`, `left`
- `ready_state`: `not_ready`, `checking`, `ready`, `blocked`
- `compatibility`: `compatible`, `version_mismatch`, `unsupported_hardware`, `unknown`

Display names are room-scoped. Seat, member ID, and tunnel direction never change during reconnect or
creator transfer.

### 3.2 Room state

Allowed room states:

```text
waiting_for_partner -> ready_check -> connection_attempt -> trading
ready_check -> waiting_for_partner
connection_attempt -> ready_check | waiting_for_partner
trading -> ready_check | closing
waiting_for_partner | ready_check | connection_attempt -> closing
closing -> closed
waiting_for_partner | ready_check -> expired
```

- `waiting_for_partner`: one occupied seat.
- `ready_check`: two seats; no locked active connection.
- `connection_attempt`: an attempt exists but trading-room entry is not confirmed.
- `trading`: both endpoints have confirmed trading-room entry.
- `closing`: authoritative teardown is in progress.
- `closed` and `expired`: terminal; no token can reopen the room.

Creator cancellation, pre-lock teardown, and a recoverable retry complete the current attempt and return
the same room and stable seats to `ready_check`. If a member leaves during `ready_check`, the room returns
to `waiting_for_partner`. If a member leaves during an unlocked `connection_attempt`, the server first
cancels/fails that attempt, releases its resources, frees the seat, and then returns the room to
`waiting_for_partner`. A locked attempt must finish bounded teardown before a seat can be freed.

### 3.3 Room profile and party references

`profile` owns the room name plus the owner's room-scoped display name, game, and language. Optional
offering, wanted, and note values are invitation/public-directory metadata and are not authoritative
room or connection state. Private clients may retain them locally for invitation copy; a public
directory must define its own reviewed record before accepting them.

`parties` contains reference/status metadata only: per member `status`, `snapshot_id`, and
`snapshot_version`. Full decoded party records exist exclusively at the party endpoint defined by
`party-commit.v1` and never appear in this room snapshot or room event stream.

## 4. Device readiness

Readiness axes remain independent:

- `local_control`
- `online_service`
- `adapter`
- `radio`
- `relay`
- `switch_connection`
- `decoder_observer`

Each axis has this shape:

```json
{
  "status": "ready",
  "user_message": "Your Wi-Fi adapter is ready.",
  "technical_code": "adapter.ready",
  "primary_action": null,
  "updated_at": "2026-08-25T12:00:03Z"
}
```

Allowed status values: `unknown`, `checking`, `ready`, `degraded`, `blocked`, `failed`, `unavailable`.
The UI may summarize these axes, but must retain the exact failing axis and recovery action.

## 5. Connection attempt

```json
{
  "attempt_id": "0199...",
  "attempt_number": 2,
  "phase": "creator_guidance",
  "creator_member_id": "0199...",
  "local_switch_role": "creator",
  "role_locked": false,
  "role_lock_version": null,
  "started_at": "2026-08-25T12:04:00Z",
  "updated_at": "2026-08-25T12:04:03Z",
  "retry_count": 1,
  "recoverable_error": null
}
```

Allowed phases:

```text
ready_check
choosing_creator
creator_guidance
finder_guidance
discovering_real_room
advertising_mirror_room
connecting_switches
trading_room
reconnecting
recovering
closing
completed
canceled
failed
```

Terminal attempt phases are `completed`, `canceled`, and `failed`.

### 5.1 Stable identity versus Switch role

The endpoint launch receives two independent axes:

```text
tunnel_seat: member_a | member_b
switch_room_role: creator | finder
```

Required radio mapping:

| Assigned Switch role | Endpoint behavior | Temporary legacy mapping |
|---|---|---|
| `creator` | Discover and join the real room created on that member's Switch | existing endpoint `host` path |
| `finder` | Open the mirrored room that the local Switch can discover | existing endpoint `guest` path |

The temporary legacy mapping is internal only and must be removed after endpoint migration. Tunnel
direction continues to derive from stable seat, never from `switch_room_role`.

## 6. Atomic creator selection

1. Both members must be online and `ready` before an attempt enters `choosing_creator`.
2. Either member may issue `claim_creator` with `command_id` and `expected_room_version`.
3. The first valid command committed by the server wins.
4. A simultaneous losing claim is not an error screen. Its response returns the new snapshot showing
   the partner as creator and the local member as finder.
5. A creator may cancel or transfer before role lock. Transfer is an authenticated atomic mutation.
6. Role lock occurs when either endpoint begins radio acquisition for the assigned attempt.
7. After lock, transfer returns `409 attempt.role_locked`; the safe action is cancel/teardown/retry.
8. Canceling returns both members to `ready_check` without changing seats.

## 7. Reconnect, leave, close, and expiration

- Heartbeat cadence: 15 seconds; offline detection after 45 seconds.
- Reconnect grace: 90 seconds for an occupied seat.
- A valid reconnect token rotates on every successful reconnect.
- During `trading_room`, a member loss enters `reconnecting`; the endpoint may buffer only within its
  existing bounded RFU policy. It must not invent remote state.
- Grace expiry fails the attempt, releases its runtime resources, and marks the member `offline` while
  retaining the seat until explicit leave, owner removal after grace, or room expiry.
- Explicit leave invalidates that member's tokens and frees the seat only when no attempt is locked.
- The owner may close the room for both; a non-owner may leave. Window close invokes the same explicit
  owner-aware action and waits for its acknowledged teardown result.
- After reconnect grace has elapsed and no attempt is locked, the owner may remove the offline member
  and reopen that seat. Before that command is acknowledged, the UI says the place is reserved.
- Waiting-for-partner expiry: 30 minutes without a second seat.
- Absolute room lifetime: 6 hours.
- Terminal room metadata may remain in the authoritative store for operational retention, but it is no
  longer joinable.

## 8. Commands

Every mutation requires `Authorization`, `Idempotency-Key`, and `If-Match: <room_version>` where a room
already exists.

| Method and path | Meaning |
|---|---|
| `POST /v1/trade-rooms` | Create private room and occupy `member_a` |
| `POST /v1/trade-rooms:join` | Locate by room code, authenticate, and atomically occupy `member_b` |
| `GET /v1/trade-rooms/{room_id}` | Fetch authoritative snapshot |
| `POST /v1/trade-rooms/{room_id}/ready` | Set local member ready/not-ready |
| `POST /v1/trade-rooms/{room_id}/attempts` | Start ready check/creator selection |
| `POST /v1/trade-rooms/{room_id}/attempts/{attempt_id}:claim-creator` | Atomic creator claim |
| `POST /v1/trade-rooms/{room_id}/attempts/{attempt_id}:transfer-creator` | Transfer before lock |
| `POST /v1/trade-rooms/{room_id}/attempts/{attempt_id}:lock-role` | Endpoint reports radio acquisition start |
| `POST /v1/trade-rooms/{room_id}/attempts/{attempt_id}:cancel` | Cancel and return to ready check |
| `POST /v1/trade-rooms/{room_id}/attempts/{attempt_id}:retry` | Create next numbered attempt |
| `POST /v1/trade-rooms/{room_id}/attempts/{attempt_id}:end` | Complete bounded teardown, invalidate parties, and return the room to ready check |
| `DELETE /v1/trade-rooms/{room_id}/members/me` | Leave safely |
| `DELETE /v1/trade-rooms/{room_id}/members/{member_id}` | Owner frees an offline seat after reconnect grace and unlocked teardown |
| `DELETE /v1/trade-rooms/{room_id}` | Owner closes room |

Retries with the same idempotency key return the original status/body and do not increment version.

The `POST /v1/trade-rooms` body is frozen as:

```json
{
  "name": "Kanto evening trades",
  "visibility": "private",
  "owner_display_name": "Leaf",
  "game": "FireRed",
  "language": "English"
}
```

For `room-control.v1`, `visibility` is `private`; a real public directory remains out of scope. Optional
offering, wanted, and note values are not accepted by this command. A client may use them locally in an
invitation or the explicitly labeled Demo Preview, but must not imply that the room service stored them.

## 9. Ordered events

Control events are JSON. RFU envelopes remain on their separate binary WebSocket path.

```json
{
  "contract_version": "room-control.v1",
  "event_id": "0199...",
  "sequence": 43,
  "room_id": "0199...",
  "room_version": 19,
  "attempt_id": "0199...",
  "type": "attempt.creator_assigned",
  "actor_member_id": "0199...",
  "occurred_at": "2026-08-25T12:04:03Z",
  "payload": {}
}
```

Required event families:

- `room.created`, `room.state_changed`, `room.closed`, `room.expired`
- `member.joined`, `member.presence_changed`, `member.readiness_changed`, `member.left`
- `attempt.created`, `attempt.creator_assigned`, `attempt.role_locked`, `attempt.phase_changed`
- `attempt.recovery_required`, `attempt.canceled`, `attempt.failed`, `attempt.completed`
- `device.readiness_changed`
- `party.snapshot.updated`, `party.snapshot.invalidated`
- `trade.committed`

Events are delivered in monotonically increasing `sequence` order. Clients reject lower/equal sequence
duplicates, detect gaps, and fetch a fresh snapshot. Reconnect uses `Last-Event-ID`; the server retains
control events for at least 24 hours. Event payloads never contain bearer tokens, raw RFU bytes, keys,
raw IP addresses, or full party data.

## 10. Local Windows/WSL control API v1

WPF talks only to loopback. The local service translates authenticated remote state and owns hardware.

| Method and path | UI use |
|---|---|
| `GET /api/v1/app/readiness` | Version compatibility and readiness axes |
| `POST /api/v1/app/retry` | Retry bounded startup/current recovery |
| `POST /api/v1/app/repair` | Run an allowlisted repair action |
| `GET /api/v1/adapters` | Detected devices plus profile and live health |
| `POST /api/v1/adapters/select` | Select by stable bus identity |
| `POST /api/v1/adapters/recheck` | Re-run health gate |
| `GET /api/v1/trade-room` | Current authoritative snapshot or `204` |
| `POST /api/v1/trade-room/create` | Create through remote authority |
| `POST /api/v1/trade-room/join` | Join through remote authority |
| `POST /api/v1/trade-room/commands` | Typed room/attempt mutation |
| `GET /api/v1/trade-room/events` | SSE stream of ordered local/UI events |
| `GET /api/v1/trade-room/parties` | Current validated local party view |
| `POST /api/v1/session/start` | Start only for assigned/locked attempt |
| `POST /api/v1/session/stop` | Bounded teardown |
| `POST /api/v1/support-bundle` | Redacted diagnostic export |

SSE is the frozen UI state-delivery mechanism. It supports `Last-Event-ID`; WPF fetches a full snapshot
on connect, gap, incompatible contract version, or server instruction. Commands are typed JSON, never a
free-form command name passed to a shell.

## 11. Error envelope and recovery actions

```json
{
  "error": {
    "code": "attempt.role_locked",
    "message": "The room roles are already in use for this connection.",
    "support_code": "ST-ATTEMPT-ROLE-LOCKED",
    "recoverable": true,
    "primary_action": "cancel_and_retry",
    "details_allowed": true
  }
}
```

Required error codes include:

- `app.version_mismatch`
- `room.not_found`, `room.full`, `room.expired`, `room.version_conflict`
- `member.unauthorized`, `member.reconnect_expired`, `member.partner_offline`
- `attempt.not_ready`, `attempt.role_locked`, `attempt.timeout`, `attempt.canceled`
- `adapter.missing`, `adapter.unsupported`, `adapter.in_use`, `adapter.rx_failed`
- `radio.room_not_found_2ghz`, `radio.room_likely_5ghz`, `radio.association_failed`
- `relay.unavailable`, `relay.reconnecting`
- `decoder.unavailable`, `decoder.invalid_snapshot`

The UI maps `primary_action` to an allowlisted command. Raw exception strings appear only inside
Technical Details or a support bundle.

Allowed `primary_action` values are:

```text
retry
repair
update
recheck_adapter
select_adapter
retry_attempt
cancel_and_retry
return_to_room
return_home
create_support_bundle
wait
dismiss
```

The client records and rejects unknown values. It never converts an error action string into a shell
command or arbitrary API request.

## 12. Version compatibility

- Every snapshot/event includes `contract_version`.
- App and local runtime exchange semantic product versions in `/api/v1/app/readiness`.
- Major contract mismatch blocks room/session commands and routes to Update/Repair.
- Minor additions must be backward compatible; clients ignore unknown JSON fields and event types after
  recording them.
- RFU envelope versioning remains independent from this control contract.

## 13. Migration from the current implementation

The current `/api/groups*`, `/api/session/start`, relay `participants`, and `host/guest` query role are
development compatibility paths only. Migration order:

1. Implement authoritative storage, member tokens, room versions, commands, and events.
2. Add local `/api/v1` snapshot/SSE translation without changing RFU bytes.
3. Split endpoint `--role` into `--tunnel-seat` and `--switch-room-role`.
4. Map assigned creator/finder to the proven legacy radio paths temporarily.
5. Move WPF from current endpoints to `/api/v1`.
6. Remove process-local participant authority and owner-derived role selection.

No installer work or final UI claim may treat the current local group dictionary as production state.
