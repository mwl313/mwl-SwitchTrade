"""Persistent two-member authority for SwitchTrade trade rooms.

The authority intentionally knows nothing about RFU or Pokemon payloads.  It stores
only room control state and SHA-256 credential hashes.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import string
import threading
import time
import uuid


CONTRACT = "room-control.v1"
ROOM_CODE_CHARS = string.ascii_uppercase + string.digits
ROOM_TTL_SECONDS = 6 * 60 * 60
RECONNECT_SECONDS = 90


class AuthorityError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def uuid7() -> str:
    """Generate an RFC 9562 UUIDv7 without requiring Python 3.14."""
    millis = int(time.time() * 1000) & ((1 << 48) - 1)
    value = millis << 80
    value |= 0x7 << 76
    value |= secrets.randbits(12) << 64
    value |= 0b10 << 62
    value |= secrets.randbits(62)
    return str(uuid.UUID(int=value))


def _utc(seconds: float | None = None) -> str:
    return datetime.fromtimestamp(seconds or time.time(), timezone.utc).isoformat().replace("+00:00", "Z")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AuthorityStore:
    """Small transactional room store shared by HTTP and WebSocket paths."""

    def __init__(self, database: str | Path):
        database = str(database)
        if database != ":memory:":
            Path(database).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(database, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._ephemeral_responses: dict[tuple[str, str], dict] = {}
        self._db.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS rooms (
                room_id TEXT PRIMARY KEY,
                room_code TEXT NOT NULL UNIQUE,
                document TEXT NOT NULL,
                expires_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS credentials (
                token_hash TEXT PRIMARY KEY,
                reconnect_hash TEXT NOT NULL UNIQUE,
                room_id TEXT NOT NULL,
                member_id TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(room_id) REFERENCES rooms(room_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS commands (
                scope TEXT NOT NULL,
                command_id TEXT NOT NULL,
                response TEXT NOT NULL,
                PRIMARY KEY(scope, command_id)
            );
            CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                room_id TEXT NOT NULL,
                room_version INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                actor_member_id TEXT,
                occurred_at TEXT NOT NULL,
                data TEXT NOT NULL,
                FOREIGN KEY(room_id) REFERENCES rooms(room_id) ON DELETE CASCADE
            );
            """
        )

    @contextmanager
    def _transaction(self):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield
            except Exception:
                self._db.execute("ROLLBACK")
                raise
            else:
                self._db.execute("COMMIT")

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _new_code(self) -> str:
        for _ in range(100):
            code = "".join(secrets.choice(ROOM_CODE_CHARS) for _ in range(6))
            if self._db.execute("SELECT 1 FROM rooms WHERE room_code=?", (code,)).fetchone() is None:
                return code
        raise AuthorityError(503, "room code allocation failed")

    def _event(self, room: dict, event_type: str, actor: str | None, data: dict | None = None) -> None:
        cursor = self._db.execute(
            "INSERT INTO events(event_id,room_id,room_version,event_type,actor_member_id,occurred_at,data) "
            "VALUES(?,?,?,?,?,?,?)",
            (uuid7(), room["room_id"], room["room_version"], event_type, actor, _utc(),
             json.dumps(data or {}, separators=(",", ":"))),
        )
        room["last_event_sequence"] = cursor.lastrowid

    def _save(self, room: dict) -> None:
        self._db.execute(
            "UPDATE rooms SET document=?, expires_at=? WHERE room_id=?",
            (json.dumps(room, separators=(",", ":")), room["expires_at_epoch"], room["room_id"]),
        )

    def _load(self, room_id: str) -> dict:
        row = self._db.execute("SELECT document FROM rooms WHERE room_id=?", (room_id,)).fetchone()
        if row is None:
            raise AuthorityError(404, "trade room not found")
        room = json.loads(row["document"])
        if room["state"] not in {"closed", "expired"} and room["expires_at_epoch"] <= time.time():
            room["state"] = "expired"
            room["room_version"] += 1
            self._event(room, "room.expired", None)
            self._save(room)
        return room

    def _credentials(self, bearer: str, room_id: str | None = None) -> tuple[dict, str]:
        if not bearer:
            raise AuthorityError(401, "member credential is required")
        row = self._db.execute(
            "SELECT room_id,member_id,active FROM credentials WHERE token_hash=?", (_hash(bearer),)
        ).fetchone()
        if row is None or not row["active"]:
            raise AuthorityError(401, "member credential is invalid")
        if room_id is not None and row["room_id"] != room_id:
            raise AuthorityError(403, "member credential does not belong to this room")
        return self._load(row["room_id"]), row["member_id"]

    @staticmethod
    def _public(room: dict, local_member_id: str) -> dict:
        value = {key: val for key, val in room.items() if key != "expires_at_epoch"}
        value["local_member_id"] = local_member_id
        value["members"] = [
            {**{key: item for key, item in member.items() if key != "last_seen_epoch"},
             "is_local": member["member_id"] == local_member_id}
            for member in room["members"]
        ]
        attempt = value.get("attempt")
        if attempt:
            attempt = dict(attempt)
            attempt["local_switch_role"] = (
                "creator" if attempt.get("creator_member_id") == local_member_id else
                "finder" if attempt.get("creator_member_id") else None
            )
            value["attempt"] = attempt
        return value

    def _command_response(self, scope: str, command_id: str) -> dict | None:
        if not command_id:
            raise AuthorityError(400, "Idempotency-Key is required")
        row = self._db.execute(
            "SELECT response FROM commands WHERE scope=? AND command_id=?", (scope, command_id)
        ).fetchone()
        return json.loads(row["response"]) if row else None

    def _remember(self, scope: str, command_id: str, response: dict) -> None:
        self._db.execute(
            "INSERT INTO commands(scope,command_id,response) VALUES(?,?,?)",
            (scope, command_id, json.dumps(response, separators=(",", ":"))),
        )

    def _secret_command_response(self, scope: str, command_id: str) -> dict | None:
        if not command_id:
            raise AuthorityError(400, "Idempotency-Key is required")
        if cached := self._ephemeral_responses.get((scope, command_id)):
            return cached
        row = self._db.execute(
            "SELECT 1 FROM commands WHERE scope=? AND command_id=?", (scope, command_id)
        ).fetchone()
        if row:
            raise AuthorityError(409, "command completed; use the reconnect flow")
        return None

    def _remember_secret(self, scope: str, command_id: str, response: dict) -> None:
        self._ephemeral_responses[(scope, command_id)] = response
        marker = {"completed": True, "room_id": response["room"]["room_id"]}
        self._remember(scope, command_id, marker)

    def create(self, payload: dict, command_id: str, client_id: str) -> dict:
        scope = f"create:{client_id or 'anonymous'}"
        with self._transaction():
            if cached := self._secret_command_response(scope, command_id):
                return cached
            name = str(payload.get("name", "")).strip()
            display = str(payload.get("trainer_display_name", "")).strip()
            game = str(payload.get("game", "None"))
            language = str(payload.get("language", "None"))
            if not name or not display or game == "None" or language == "None":
                raise AuthorityError(400, "room name, trainer name, game, and language are required")
            now = time.time()
            room_id, member_id, code = uuid7(), uuid7(), self._new_code()
            token, reconnect = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            room = {
                "contract_version": CONTRACT,
                "room_id": room_id,
                "room_version": 1,
                "name": name[:80],
                "visibility": "private",
                "room_code": code,
                "profile": {
                    "owner_display_name": display[:40], "game": game[:20], "language": language[:20]
                },
                "owner_member_id": member_id,
                "state": "waiting_for_partner",
                "created_at": _utc(now),
                "expires_at": _utc(now + ROOM_TTL_SECONDS),
                "expires_at_epoch": now + ROOM_TTL_SECONDS,
                "members": [{
                    "member_id": member_id, "seat": "member_a", "display_name": display[:40],
                    "online_state": "online", "ready_state": "not_ready",
                    "compatibility": "compatible", "joined_at": _utc(now),
                    "reconnect_deadline": None, "last_seen_epoch": now,
                }],
                "attempt": None,
                "device_readiness": {},
                "parties": {
                    seat: {"status": "unavailable", "snapshot_id": None, "snapshot_version": None}
                    for seat in ("member_a", "member_b")
                },
                "last_event_sequence": 0,
            }
            self._db.execute(
                "INSERT INTO rooms(room_id,room_code,document,expires_at) VALUES(?,?,?,?)",
                (room_id, code, "{}", room["expires_at_epoch"]),
            )
            self._db.execute(
                "INSERT INTO credentials(token_hash,reconnect_hash,room_id,member_id) VALUES(?,?,?,?)",
                (_hash(token), _hash(reconnect), room_id, member_id),
            )
            self._event(room, "room.created", member_id)
            self._save(room)
            response = {"room": self._public(room, member_id), "member_token": token,
                        "reconnect_token": reconnect}
            self._remember_secret(scope, command_id, response)
            return response

    def join(self, payload: dict, command_id: str, client_id: str) -> dict:
        code = str(payload.get("room_code", "")).strip().upper()
        display = str(payload.get("trainer_display_name", "Trainer")).strip() or "Trainer"
        scope = f"join:{client_id or 'anonymous'}:{code}"
        with self._transaction():
            if cached := self._secret_command_response(scope, command_id):
                return cached
            row = self._db.execute("SELECT room_id FROM rooms WHERE room_code=?", (code,)).fetchone()
            if row is None:
                raise AuthorityError(404, "trade room not found")
            room = self._load(row["room_id"])
            if room["state"] in {"closed", "expired"}:
                raise AuthorityError(410, "trade room is no longer available")
            if len([m for m in room["members"] if m["online_state"] != "left"]) >= 2:
                raise AuthorityError(409, "trade room is full")
            member_id, token, reconnect = uuid7(), secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            room["members"] = [member for member in room["members"]
                               if member["online_state"] != "left"]
            room["members"].append({
                "member_id": member_id, "seat": "member_b", "display_name": display[:40],
                "online_state": "online", "ready_state": "not_ready",
                "compatibility": "compatible", "joined_at": _utc(), "reconnect_deadline": None,
                "last_seen_epoch": time.time(),
            })
            room["state"] = "ready_check"
            room["room_version"] += 1
            self._db.execute(
                "INSERT INTO credentials(token_hash,reconnect_hash,room_id,member_id) VALUES(?,?,?,?)",
                (_hash(token), _hash(reconnect), room["room_id"], member_id),
            )
            self._event(room, "member.joined", member_id, {"seat": "member_b"})
            self._save(room)
            response = {"room": self._public(room, member_id), "member_token": token,
                        "reconnect_token": reconnect}
            self._remember_secret(scope, command_id, response)
            return response

    def snapshot(self, room_id: str, bearer: str) -> dict:
        with self._lock:
            room, member_id = self._credentials(bearer, room_id)
            return self._public(room, member_id)

    def snapshot_for_token(self, bearer: str) -> dict:
        with self._lock:
            room, member_id = self._credentials(bearer)
            return self._public(room, member_id)

    def member_for_code(self, room_code: str, bearer: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT room_id FROM rooms WHERE room_code=?", (room_code,)).fetchone()
            if row is None:
                return None
            room, member_id = self._credentials(bearer, row["room_id"])
            member = next(item for item in room["members"] if item["member_id"] == member_id)
            return {"room_id": room["room_id"], "member_id": member_id, "seat": member["seat"]}

    def has_code(self, room_code: str) -> bool:
        with self._lock:
            return self._db.execute(
                "SELECT 1 FROM rooms WHERE room_code=?", (room_code,)
            ).fetchone() is not None

    def operational_stats(self) -> dict:
        with self._lock:
            states: dict[str, int] = {}
            for row in self._db.execute("SELECT document FROM rooms"):
                room = json.loads(row["document"])
                state = room.get("state", "unknown")
                states[state] = states.get(state, 0) + 1
            return {
                "rooms_by_state": states,
                "active_member_credentials": self._db.execute(
                    "SELECT COUNT(*) FROM credentials WHERE active=1").fetchone()[0],
                "ordered_events": self._db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
            }

    def mutate(self, room_id: str, bearer: str, command_id: str, action: str,
               payload: dict | None = None) -> dict:
        payload = payload or {}
        with self._transaction():
            room, member_id = self._credentials(bearer, room_id)
            scope = f"member:{member_id}:{action}"
            if cached := self._command_response(scope, command_id):
                return cached
            if room["state"] in {"closed", "expired"}:
                raise AuthorityError(409, "trade room is not active")
            member = next(item for item in room["members"] if item["member_id"] == member_id)
            event = action
            if action in {"claim_creator", "transfer_creator", "lock_role", "phase"}:
                current_attempt = room.get("attempt")
                if not current_attempt or payload.get("attempt_id") != current_attempt.get("attempt_id"):
                    raise AuthorityError(409, "connection attempt is stale")
            if action == "ready":
                ready = bool(payload.get("ready", True))
                member["ready_state"] = "ready" if ready else "not_ready"
                event = "member.ready" if ready else "member.not_ready"
            elif action == "heartbeat":
                member["online_state"] = "online"
                member["reconnect_deadline"] = None
                member["last_seen_epoch"] = time.time()
                event = "member.heartbeat"
            elif action == "attempt":
                active = [m for m in room["members"] if m["online_state"] != "left"]
                if len(active) != 2 or any(m["ready_state"] != "ready" for m in active):
                    raise AuthorityError(409, "both members must be ready")
                number = (room.get("last_attempt_number") or 0) + 1
                room["last_attempt_number"] = number
                room["attempt"] = {
                    "attempt_id": uuid7(), "attempt_number": number,
                    "phase": "choosing_creator", "creator_member_id": None,
                    "role_locked": False, "role_lock_version": None,
                    "started_at": _utc(), "updated_at": _utc(), "retry_count": 0,
                    "recoverable_error": None,
                }
                room["state"] = "connection_attempt"
                event = "attempt.started"
            elif action == "claim_creator":
                attempt = room.get("attempt")
                if not attempt or attempt["role_locked"]:
                    raise AuthorityError(409, "creator role cannot be claimed")
                if attempt["creator_member_id"] is None:
                    attempt["creator_member_id"] = member_id
                    attempt["phase"] = "creator_guidance"
                    attempt["updated_at"] = _utc()
                event = "attempt.creator_claimed"
            elif action == "transfer_creator":
                attempt = room.get("attempt")
                if not attempt or attempt["role_locked"] or attempt["creator_member_id"] != member_id:
                    raise AuthorityError(409, "creator role cannot be transferred")
                target = str(payload.get("target_member_id", ""))
                if target not in {m["member_id"] for m in room["members"] if m["online_state"] != "left"}:
                    raise AuthorityError(400, "target member is not active")
                attempt["creator_member_id"] = target
                attempt["updated_at"] = _utc()
                event = "attempt.creator_transferred"
            elif action == "lock_role":
                attempt = room.get("attempt")
                if not attempt or not attempt["creator_member_id"]:
                    raise AuthorityError(409, "creator role has not been assigned")
                attempt["role_locked"] = True
                attempt["role_lock_version"] = room["room_version"] + 1
                attempt["phase"] = "connecting_switches"
                attempt["updated_at"] = _utc()
                event = "attempt.role_locked"
            elif action == "phase":
                phase = str(payload.get("phase", ""))
                allowed = {"discovering_real_room", "advertising_mirror_room", "connecting_switches",
                           "trading_room", "reconnecting", "recovering", "closing", "completed",
                           "canceled", "failed"}
                if phase not in allowed or not room.get("attempt"):
                    raise AuthorityError(400, "invalid attempt phase")
                room["attempt"]["phase"] = phase
                room["attempt"]["updated_at"] = _utc()
                if phase == "trading_room":
                    room["state"] = "trading"
                elif phase in {"completed", "canceled", "failed"}:
                    room["state"] = "ready_check"
                event = f"attempt.{phase}"
            elif action == "leave":
                if room["owner_member_id"] == member_id:
                    raise AuthorityError(409, "the room owner must close the room")
                if room.get("attempt") and room["attempt"].get("role_locked"):
                    raise AuthorityError(409, "finish connection teardown before leaving")
                member["online_state"] = "left"
                member["ready_state"] = "not_ready"
                room["attempt"] = None
                room["state"] = "waiting_for_partner"
                self._db.execute(
                    "UPDATE credentials SET active=0 WHERE room_id=? AND member_id=?",
                    (room_id, member_id),
                )
                event = "member.left"
            elif action == "close":
                if room["owner_member_id"] != member_id:
                    raise AuthorityError(403, "only the room owner can close this room")
                room["state"] = "closed"
                self._db.execute("UPDATE credentials SET active=0 WHERE room_id=?", (room_id,))
                event = "room.closed"
            else:
                raise AuthorityError(404, "unknown room command")
            room["room_version"] += 1
            self._event(room, event, member_id, payload)
            self._save(room)
            response = self._public(room, member_id)
            self._remember(scope, command_id, response)
            return response

    def reconnect(self, room_id: str, reconnect_token: str) -> dict:
        with self._transaction():
            row = self._db.execute(
                "SELECT token_hash,member_id,active FROM credentials WHERE reconnect_hash=? AND room_id=?",
                (_hash(reconnect_token), room_id),
            ).fetchone()
            if row is None or not row["active"]:
                raise AuthorityError(401, "reconnect credential is invalid")
            room = self._load(room_id)
            member = next(item for item in room["members"] if item["member_id"] == row["member_id"])
            deadline = member.get("reconnect_deadline")
            if deadline and datetime.fromisoformat(deadline.replace("Z", "+00:00")).timestamp() < time.time():
                raise AuthorityError(410, "reconnect deadline expired")
            token, reconnect = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            self._db.execute(
                "UPDATE credentials SET token_hash=?,reconnect_hash=? WHERE reconnect_hash=?",
                (_hash(token), _hash(reconnect), _hash(reconnect_token)),
            )
            member["online_state"] = "online"
            member["reconnect_deadline"] = None
            member["last_seen_epoch"] = time.time()
            room["room_version"] += 1
            self._event(room, "member.reconnected", member["member_id"])
            self._save(room)
            return {"room": self._public(room, member["member_id"]), "member_token": token,
                    "reconnect_token": reconnect}

    def events(self, room_id: str, bearer: str, after: int = 0, limit: int = 100) -> dict:
        with self._lock:
            room, member_id = self._credentials(bearer, room_id)
            rows = self._db.execute(
                "SELECT * FROM events WHERE room_id=? AND sequence>? ORDER BY sequence LIMIT ?",
                (room_id, max(0, after), max(1, min(limit, 100))),
            ).fetchall()
            return {
                "contract_version": CONTRACT,
                "room_id": room_id,
                "local_member_id": member_id,
                "events": [{
                    "sequence": row["sequence"], "event_id": row["event_id"],
                    "room_version": row["room_version"], "type": row["event_type"],
                    "actor_member_id": row["actor_member_id"], "occurred_at": row["occurred_at"],
                    "data": json.loads(row["data"]),
                } for row in rows],
                "last_event_sequence": room["last_event_sequence"],
            }

    def sweep_presence(self) -> None:
        now = time.time()
        with self._transaction():
            rows = self._db.execute("SELECT room_id,document FROM rooms").fetchall()
            for row in rows:
                room = json.loads(row["document"])
                if room["state"] in {"closed", "expired"}:
                    continue
                changed = False
                for member in room["members"]:
                    if member["online_state"] == "online" and now - member.get("last_seen_epoch", now) > 30:
                        member["online_state"] = "reconnecting"
                        member["reconnect_deadline"] = _utc(now + RECONNECT_SECONDS)
                        changed = True
                        event = "member.reconnecting"
                    elif member["online_state"] == "reconnecting" and member.get("reconnect_deadline"):
                        deadline = datetime.fromisoformat(
                            member["reconnect_deadline"].replace("Z", "+00:00")).timestamp()
                        if deadline <= now:
                            member["online_state"] = "offline"
                            changed = True
                            event = "member.offline"
                    else:
                        continue
                    room["room_version"] += 1
                    self._event(room, event, member["member_id"])
                if changed:
                    self._save(room)
