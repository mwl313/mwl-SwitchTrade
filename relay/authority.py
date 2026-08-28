"""Persistent two-member authority for SwitchTrade trade rooms.

The authority intentionally knows nothing about RFU or Pokemon payloads.  It stores
only room control state and SHA-256 credential hashes.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import string
import threading
import time
import uuid

from switchtrade.process_guard import SingleInstanceLock


CONTRACT = "room-control.v1"
PUBLIC_DIRECTORY_CONTRACT = "public-directory.v1"
ROOM_CODE_CHARS = string.ascii_uppercase + string.digits
ROOM_TTL_SECONDS = 6 * 60 * 60
WAITING_TTL_SECONDS = 30 * 60
OFFLINE_DETECTION_SECONDS = 45
RECONNECT_SECONDS = 90
SECRET_RESPONSE_SECONDS = 10 * 60
COMMAND_RETENTION_SECONDS = 24 * 60 * 60
AUTHORITY_RETENTION_SECONDS = 14 * 24 * 60 * 60
TERMINAL_ATTEMPT_PHASES = {"completed", "canceled", "failed"}
ATTEMPT_PHASE_ORDER = {
    "creator_guidance": 0,
    "connecting_switches": 1,
    "discovering_real_room": 2,
    "advertising_mirror_room": 2,
    "trading_room": 3,
    "reconnecting": 4,
    "recovering": 5,
    "closing": 6,
    "completed": 7,
    "canceled": 7,
    "failed": 7,
}


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


def _database_writer_lock(database: str | Path) -> SingleInstanceLock:
    resolved = Path(database).resolve()
    lock_name = "relay-writer-" + hashlib.sha256(
        os.fsencode(os.path.normcase(str(resolved)))).hexdigest()[:16]
    return SingleInstanceLock(lock_name, resolved.parent)


def _validate_database(connection: sqlite3.Connection) -> None:
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise sqlite3.DatabaseError("authority database integrity check failed")
    tables = {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")
    }
    required = {"rooms", "credentials", "commands", "events"}
    if not required <= tables:
        raise sqlite3.DatabaseError("authority database schema is incomplete")


def copy_database(source: str | Path, destination: str | Path) -> None:
    """Create or restore one atomic, WAL-consistent SQLite snapshot."""
    source_path, destination_path = Path(source).resolve(), Path(destination).resolve()
    if source_path == destination_path:
        raise ValueError("source and destination databases must differ")
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination_path.with_name(
        f".{destination_path.name}.{uuid.uuid4().hex}.tmp")
    with _database_writer_lock(destination_path):
        try:
            source_db = sqlite3.connect(f"{source_path.as_uri()}?mode=ro", uri=True)
            try:
                destination_db = sqlite3.connect(temporary)
                try:
                    source_db.backup(destination_db)
                    _validate_database(destination_db)
                finally:
                    destination_db.close()
            finally:
                source_db.close()
            for suffix in ("-wal", "-shm"):
                destination_path.with_name(destination_path.name + suffix).unlink(missing_ok=True)
            os.replace(temporary, destination_path)
        finally:
            temporary.unlink(missing_ok=True)


class AuthorityStore:
    """Small transactional room store shared by HTTP and WebSocket paths."""

    def __init__(self, database: str | Path):
        database = str(database)
        self.database = database
        self._writer_lock = None
        if database != ":memory:":
            resolved = Path(database).resolve()
            resolved.parent.mkdir(parents=True, exist_ok=True)
            self._writer_lock = _database_writer_lock(resolved).acquire()
        try:
            self._db = sqlite3.connect(database, check_same_thread=False, isolation_level=None)
        except Exception:
            if self._writer_lock is not None:
                self._writer_lock.close()
            raise
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._ephemeral_responses: dict[tuple[str, str], tuple[float, dict]] = {}
        self._db.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS rooms (
                room_id TEXT PRIMARY KEY,
                room_code TEXT NOT NULL UNIQUE,
                directory_id TEXT UNIQUE,
                document TEXT NOT NULL,
                expires_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS credentials (
                token_hash TEXT PRIMARY KEY,
                reconnect_hash TEXT NOT NULL UNIQUE,
                previous_reconnect_hash TEXT,
                previous_reconnect_until REAL,
                room_id TEXT NOT NULL,
                member_id TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(room_id) REFERENCES rooms(room_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS commands (
                scope TEXT NOT NULL,
                command_id TEXT NOT NULL,
                response TEXT NOT NULL,
                created_at REAL NOT NULL,
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
            CREATE TABLE IF NOT EXISTS service_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT OR IGNORE INTO service_state(key,value) VALUES('readiness','initialized');
            """
        )
        columns = {row[1] for row in self._db.execute("PRAGMA table_info(commands)")}
        if "created_at" not in columns:
            self._db.execute("ALTER TABLE commands ADD COLUMN created_at REAL NOT NULL DEFAULT 0")
            self._db.execute("UPDATE commands SET created_at=? WHERE created_at=0", (time.time(),))
        credential_columns = {
            row[1] for row in self._db.execute("PRAGMA table_info(credentials)")
        }
        if "previous_reconnect_hash" not in credential_columns:
            self._db.execute("ALTER TABLE credentials ADD COLUMN previous_reconnect_hash TEXT")
        if "previous_reconnect_until" not in credential_columns:
            self._db.execute("ALTER TABLE credentials ADD COLUMN previous_reconnect_until REAL")
        room_columns = {row[1] for row in self._db.execute("PRAGMA table_info(rooms)")}
        if "directory_id" not in room_columns:
            self._db.execute("ALTER TABLE rooms ADD COLUMN directory_id TEXT")
        self._db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS rooms_directory_id ON rooms(directory_id)"
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
            try:
                self._db.close()
            finally:
                if self._writer_lock is not None:
                    self._writer_lock.close()
                    self._writer_lock = None

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
        now = time.time()
        waiting_expired = (
            room["state"] == "waiting_for_partner" and
            room.get("waiting_expires_at_epoch", room["expires_at_epoch"]) <= now
        )
        if room["state"] not in {"closed", "expired"} and (
                room["expires_at_epoch"] <= now or waiting_expired):
            if not self._db.in_transaction:
                with self._transaction():
                    return self._load(room_id)
            room["state"] = "expired"
            room["room_version"] += 1
            self._event(room, "room.expired", None)
            self._db.execute("UPDATE credentials SET active=0 WHERE room_id=?", (room_id,))
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
        value = {
            key: val for key, val in room.items()
            if key not in {"expires_at_epoch", "waiting_expires_at_epoch"}
        }
        value["local_member_id"] = local_member_id
        value["members"] = [
            {**{key: item for key, item in member.items() if key != "last_seen_epoch"},
             "is_local": member["member_id"] == local_member_id}
            for member in room["members"]
        ]
        attempt = value.get("attempt")
        if attempt:
            attempt = dict(attempt)
            active_attempt = attempt.get("phase") not in {"completed", "canceled", "failed"}
            attempt["local_switch_role"] = (
                "creator" if active_attempt and attempt.get("creator_member_id") == local_member_id else
                "finder" if active_attempt and attempt.get("creator_member_id") else None
            )
            value["attempt"] = attempt
        return value

    @staticmethod
    def _directory_listing(room: dict) -> dict:
        metadata = room.get("directory") or {}
        active_members = [
            member for member in room.get("members", [])
            if member.get("online_state") != "left"
        ]
        return {
            "contract_version": PUBLIC_DIRECTORY_CONTRACT,
            "listing_id": metadata.get("listing_id"),
            "room_name": room.get("name", "Trade Room"),
            "trainer_display_name": (room.get("profile") or {}).get(
                "owner_display_name", "Trainer"),
            "game": (room.get("profile") or {}).get("game", "None"),
            "language": (room.get("profile") or {}).get("language", "None"),
            "offering": metadata.get("offering", ""),
            "wanted": metadata.get("wanted", ""),
            "note": metadata.get("note", ""),
            "availability": "open" if len(active_members) < 2 else "full",
            "occupancy": len(active_members),
            "capacity": 2,
            "created_at": room.get("created_at"),
        }

    @staticmethod
    def _owner_available(room: dict) -> bool:
        owner_id = room.get("owner_member_id")
        owner = next(
            (member for member in room.get("members", [])
             if member.get("member_id") == owner_id), None)
        return bool(owner and owner.get("online_state") in {"online", "reconnecting"})

    def _command_response(self, scope: str, command_id: str) -> dict | None:
        if not command_id:
            raise AuthorityError(400, "Idempotency-Key is required")
        row = self._db.execute(
            "SELECT response FROM commands WHERE scope=? AND command_id=?", (scope, command_id)
        ).fetchone()
        return json.loads(row["response"]) if row else None

    def _remember(self, scope: str, command_id: str, response: dict) -> None:
        self._db.execute(
            "INSERT INTO commands(scope,command_id,response,created_at) VALUES(?,?,?,?)",
            (scope, command_id, json.dumps(response, separators=(",", ":")), time.time()),
        )

    def _secret_command_response(self, scope: str, command_id: str) -> dict | None:
        if not command_id:
            raise AuthorityError(400, "Idempotency-Key is required")
        now = time.time()
        if len(self._ephemeral_responses) >= 4096:
            self._ephemeral_responses = {
                key: value for key, value in self._ephemeral_responses.items() if value[0] > now
            }
            if len(self._ephemeral_responses) >= 4096 and (scope, command_id) not in self._ephemeral_responses:
                raise AuthorityError(503, "room command cache is at capacity")
        if cached := self._ephemeral_responses.get((scope, command_id)):
            if cached[0] > now:
                return cached[1]
            self._ephemeral_responses.pop((scope, command_id), None)
        row = self._db.execute(
            "SELECT 1 FROM commands WHERE scope=? AND command_id=?", (scope, command_id)
        ).fetchone()
        if row:
            raise AuthorityError(409, "command completed; use the reconnect flow")
        return None

    def _remember_secret(self, scope: str, command_id: str, response: dict) -> None:
        self._ephemeral_responses[(scope, command_id)] = (
            time.time() + SECRET_RESPONSE_SECONDS, response)
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
            visibility = str(payload.get("visibility", "private"))
            if not name or not display or game == "None" or language == "None":
                raise AuthorityError(400, "room name, trainer name, game, and language are required")
            if len(name) > 22 or len(display) > 20:
                raise AuthorityError(400, "room name or trainer name is too long")
            if visibility not in {"private", "public"}:
                raise AuthorityError(400, "room visibility is invalid")
            offering = str(payload.get("offering", "")).strip()
            wanted = str(payload.get("wanted", "")).strip()
            note = str(payload.get("note", "")).strip()
            if len(offering) > 80 or len(wanted) > 80 or len(note) > 120:
                raise AuthorityError(400, "public room metadata is too long")
            now = time.time()
            room_id, member_id, code = uuid7(), uuid7(), self._new_code()
            directory_id = uuid7() if visibility == "public" else None
            token, reconnect = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            room = {
                "contract_version": CONTRACT,
                "room_id": room_id,
                "room_version": 1,
                "name": name,
                "visibility": visibility,
                "room_code": code,
                "profile": {
                    "owner_display_name": display, "game": game[:20], "language": language[:20]
                },
                "owner_member_id": member_id,
                "state": "waiting_for_partner",
                "created_at": _utc(now),
                "expires_at": _utc(now + ROOM_TTL_SECONDS),
                "expires_at_epoch": now + ROOM_TTL_SECONDS,
                "waiting_expires_at_epoch": now + WAITING_TTL_SECONDS,
                "members": [{
                    "member_id": member_id, "seat": "member_a", "display_name": display[:40],
                    "online_state": "online", "ready_state": "not_ready",
                    "switch_room_role": None,
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
            if directory_id:
                room["directory"] = {
                    "listing_id": directory_id,
                    "offering": offering[:80],
                    "wanted": wanted[:80],
                    "note": note[:120],
                }
            self._db.execute(
                "INSERT INTO rooms(room_id,room_code,directory_id,document,expires_at) "
                "VALUES(?,?,?,?,?)",
                (room_id, code, directory_id, "{}", room["expires_at_epoch"]),
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

    def list_public(self, query: str = "", game: str = "", language: str = "",
                    availability: str = "open", sort: str = "recent",
                    cursor: int = 0, limit: int = 25) -> dict:
        query = query.strip().casefold()[:80]
        cursor = max(0, cursor)
        limit = max(1, min(limit, 50))
        with self._lock:
            rooms: list[dict] = []
            rows = self._db.execute(
                "SELECT room_id FROM rooms WHERE directory_id IS NOT NULL"
            ).fetchall()
            for row in rows:
                room = self._load(row["room_id"])
                if (room.get("state") in {"closed", "expired"} or
                        not self._owner_available(room)):
                    continue
                listing = self._directory_listing(room)
                if availability == "open" and listing["availability"] != "open":
                    continue
                if game and listing["game"] != game:
                    continue
                if language and listing["language"] != language:
                    continue
                if query and not any(query in str(listing[field]).casefold() for field in (
                        "room_name", "trainer_display_name", "offering", "wanted")):
                    continue
                rooms.append(listing)

            if sort == "name":
                rooms.sort(key=lambda item: (item["room_name"].casefold(), item["created_at"] or ""))
            elif sort == "oldest":
                rooms.sort(key=lambda item: item["created_at"] or "")
            else:
                rooms.sort(key=lambda item: item["created_at"] or "", reverse=True)
            page = rooms[cursor:cursor + limit]
            next_cursor = cursor + len(page) if cursor + len(page) < len(rooms) else None
            return {
                "contract_version": PUBLIC_DIRECTORY_CONTRACT,
                "rooms": page,
                "next_cursor": str(next_cursor) if next_cursor is not None else None,
            }

    def public_details(self, listing_id: str) -> dict:
        with self._lock:
            row = self._db.execute(
                "SELECT room_id FROM rooms WHERE directory_id=?", (listing_id,)
            ).fetchone()
            if row is None:
                raise AuthorityError(404, "public room not found")
            room = self._load(row["room_id"])
            if (room.get("state") in {"closed", "expired"} or
                    not self._owner_available(room)):
                raise AuthorityError(410, "public room is stale")
            return self._directory_listing(room)

    def join_public(self, listing_id: str, display_name: str,
                    command_id: str, client_id: str) -> dict:
        display_name = display_name.strip() or "Trainer"
        scope = f"public-join:{client_id or 'anonymous'}:{listing_id}"
        with self._transaction():
            if cached := self._secret_command_response(scope, command_id):
                return cached
            row = self._db.execute(
                "SELECT room_id FROM rooms WHERE directory_id=?", (listing_id,)
            ).fetchone()
            if row is None:
                raise AuthorityError(404, "public room not found")
            room = self._load(row["room_id"])
            if (room.get("state") in {"closed", "expired"} or
                    not self._owner_available(room)):
                raise AuthorityError(410, "public room is stale")
            return self._join_room(room, display_name, scope, command_id)

    def _join_room(self, room: dict, display: str, scope: str, command_id: str) -> dict:
        if len([m for m in room["members"] if m["online_state"] != "left"]) >= 2:
            raise AuthorityError(409, "trade room is full")
        member_id, token, reconnect = uuid7(), secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        room["members"] = [member for member in room["members"]
                           if member["online_state"] != "left"]
        room["members"].append({
            "member_id": member_id, "seat": "member_b", "display_name": display[:40],
            "online_state": "online", "ready_state": "not_ready",
            "switch_room_role": None,
            "compatibility": "compatible", "joined_at": _utc(), "reconnect_deadline": None,
            "last_seen_epoch": time.time(),
        })
        room["state"] = "ready_check"
        room["waiting_expires_at_epoch"] = None
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
            return self._join_room(room, display, scope, command_id)

    def snapshot(self, room_id: str, bearer: str) -> dict:
        with self._lock:
            room, member_id = self._credentials(bearer, room_id)
            return self._public(room, member_id)

    def snapshot_for_token(self, bearer: str) -> dict:
        with self._lock:
            room, member_id = self._credentials(bearer)
            return self._public(room, member_id)

    def member_for_code(self, room_code: str, bearer: str,
                        attempt_id: str | None = None) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT room_id FROM rooms WHERE room_code=?", (room_code,)).fetchone()
            if row is None:
                return None
            room, member_id = self._credentials(bearer, row["room_id"])
            if attempt_id is not None:
                attempt = room.get("attempt") or {}
                if (attempt.get("attempt_id") != attempt_id or not attempt.get("role_locked") or
                        attempt.get("phase") in {"completed", "canceled", "failed"}):
                    raise AuthorityError(409, "connection attempt is not active")
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

    def ping(self) -> None:
        with self._transaction():
            self._db.execute(
                "UPDATE service_state SET value=? WHERE key='readiness'", (_utc(),))
            if self._db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("authority database integrity check failed")

    @staticmethod
    def _begin_attempt(room: dict, active: list[dict]) -> None:
        creator = next(
            member["member_id"] for member in active
            if member["switch_room_role"] == "creator")
        number = (room.get("last_attempt_number") or 0) + 1
        room["last_attempt_number"] = number
        room["attempt"] = {
            "attempt_id": uuid7(), "attempt_number": number,
            "phase": "connecting_switches", "creator_member_id": creator,
            "role_locked": True, "role_lock_version": room["room_version"] + 1,
            "started_at": _utc(), "updated_at": _utc(), "retry_count": 0,
            "recoverable_error": None,
        }
        room["state"] = "connection_attempt"

    def mutate(self, room_id: str, bearer: str, command_id: str, action: str,
               payload: dict | None = None, expected_version: int | None = None) -> dict:
        payload = payload or {}
        with self._transaction():
            room, member_id = self._credentials(bearer, room_id)
            scope = f"member:{member_id}:{action}"
            if cached := self._command_response(scope, command_id):
                return cached
            if room["state"] in {"closed", "expired"}:
                raise AuthorityError(409, "trade room is not active")
            if expected_version is not None and expected_version != room["room_version"]:
                attempt = room.get("attempt") or {}
                if (action == "attempt" and
                        attempt.get("phase") not in {None, "completed", "canceled", "failed"}):
                    response = self._public(room, member_id)
                    self._remember(scope, command_id, response)
                    return response
                if (action == "claim_creator" and attempt.get("creator_member_id") and
                        payload.get("attempt_id") == attempt.get("attempt_id")):
                    response = self._public(room, member_id)
                    self._remember(scope, command_id, response)
                    return response
                if action not in {"ready", "heartbeat", "leave", "close"}:
                    raise AuthorityError(409, "room version conflict")
            member = next(item for item in room["members"] if item["member_id"] == member_id)
            event = action
            if action in {"claim_creator", "transfer_creator", "lock_role", "phase"}:
                current_attempt = room.get("attempt")
                if not current_attempt or payload.get("attempt_id") != current_attempt.get("attempt_id"):
                    raise AuthorityError(409, "connection attempt is stale")
            if action == "ready":
                ready = bool(payload.get("ready", True))
                role = payload.get("switch_room_role")
                if ready and role not in {"creator", "finder"}:
                    raise AuthorityError(400, "choose Group Leader or Joining before connecting")
                member["ready_state"] = "ready" if ready else "not_ready"
                member["switch_room_role"] = role if ready else None
                event = "member.ready" if ready else "member.not_ready"
                active = [m for m in room["members"] if m["online_state"] != "left"]
                current = room.get("attempt")
                if (not ready and current and
                        current.get("phase") in TERMINAL_ATTEMPT_PHASES):
                    room["attempt"] = None
                    current = None
                if current and current.get("phase") not in {"completed", "canceled", "failed"}:
                    if (member["ready_state"] != "ready" or
                            member["switch_room_role"] != self._public(room, member_id)["attempt"]["local_switch_role"]):
                        raise AuthorityError(409, "finish connection teardown before changing roles")
                elif (len(active) == 2 and all(m["ready_state"] == "ready" for m in active) and
                      {m.get("switch_room_role") for m in active} == {"creator", "finder"}):
                    self._begin_attempt(room, active)
                    event = "attempt.started"
                elif ready:
                    room["state"] = "waiting_for_complementary_role"
                else:
                    room["state"] = "ready_check"
            elif action == "heartbeat":
                member["online_state"] = "online"
                member["reconnect_deadline"] = None
                member["last_seen_epoch"] = time.time()
                event = "member.heartbeat"
            elif action == "attempt":
                current = room.get("attempt")
                if current and current.get("phase") not in {"completed", "canceled", "failed"}:
                    response = self._public(room, member_id)
                    self._remember(scope, command_id, response)
                    return response
                active = [m for m in room["members"] if m["online_state"] != "left"]
                if len(active) != 2 or any(m["ready_state"] != "ready" for m in active):
                    raise AuthorityError(409, "both members must be ready")
                roles = {member.get("switch_room_role") for member in active}
                if roles != {"creator", "finder"}:
                    raise AuthorityError(
                        409, "one trainer must choose Group Leader and the other must choose Joining")
                self._begin_attempt(room, active)
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
                if phase not in ATTEMPT_PHASE_ORDER or not room.get("attempt"):
                    raise AuthorityError(400, "invalid attempt phase")
                failure_code = None
                if phase == "failed":
                    failure_code = str(payload.get("failure_code") or "session.failed")
                    if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", failure_code):
                        raise AuthorityError(400, "invalid attempt failure code")
                current_phase = str(room["attempt"].get("phase", ""))
                if current_phase == phase:
                    if (phase == "failed" and
                            room["attempt"].get("recoverable_error") == "relay.peer_lost" and
                            failure_code != "relay.peer_lost"):
                        room["attempt"]["recoverable_error"] = failure_code
                        room["attempt"]["updated_at"] = _utc()
                        event = "attempt.failure_refined"
                    else:
                        response = self._public(room, member_id)
                        self._remember(scope, command_id, response)
                        return response
                elif (current_phase in TERMINAL_ATTEMPT_PHASES or
                        ATTEMPT_PHASE_ORDER.get(current_phase, -1) > ATTEMPT_PHASE_ORDER[phase]):
                    raise AuthorityError(409, "attempt phase cannot move backward")
                else:
                    room["attempt"]["phase"] = phase
                    if failure_code is not None:
                        room["attempt"]["recoverable_error"] = failure_code
                    room["attempt"]["updated_at"] = _utc()
                    if phase == "trading_room":
                        room["state"] = "trading"
                    elif phase in {"completed", "canceled", "failed"}:
                        room["state"] = "ready_check"
                        for active_member in room["members"]:
                            if active_member["online_state"] != "left":
                                active_member["ready_state"] = "not_ready"
                                active_member["switch_room_role"] = None
                    event = f"attempt.{phase}"
            elif action == "leave":
                if room["owner_member_id"] == member_id:
                    raise AuthorityError(409, "the room owner must close the room")
                attempt = room.get("attempt") or {}
                if (attempt.get("role_locked") and
                        attempt.get("phase") not in {"completed", "canceled", "failed"}):
                    raise AuthorityError(409, "finish connection teardown before leaving")
                member["online_state"] = "left"
                for active_member in room["members"]:
                    active_member["ready_state"] = "not_ready"
                    active_member["switch_room_role"] = None
                room["attempt"] = None
                room["state"] = "waiting_for_partner"
                room["waiting_expires_at_epoch"] = min(
                    time.time() + WAITING_TTL_SECONDS, room["expires_at_epoch"])
                self._db.execute(
                    "UPDATE credentials SET active=0 WHERE room_id=? AND member_id=?",
                    (room_id, member_id),
                )
                event = "member.left"
            elif action == "remove_offline":
                if room["owner_member_id"] != member_id:
                    raise AuthorityError(403, "only the room owner can remove an offline member")
                attempt = room.get("attempt") or {}
                if (attempt.get("role_locked") and
                        attempt.get("phase") not in {"completed", "canceled", "failed"}):
                    raise AuthorityError(409, "finish connection teardown before removing a member")
                target = str(payload.get("target_member_id", ""))
                target_member = next(
                    (item for item in room["members"] if item["member_id"] == target), None)
                if target_member is None or target_member["member_id"] == member_id:
                    raise AuthorityError(400, "offline member is invalid")
                if target_member["online_state"] != "offline":
                    raise AuthorityError(409, "member reconnect grace has not expired")
                target_member["online_state"] = "left"
                for active_member in room["members"]:
                    active_member["ready_state"] = "not_ready"
                    active_member["switch_room_role"] = None
                room["attempt"] = None
                room["state"] = "waiting_for_partner"
                room["waiting_expires_at_epoch"] = min(
                    time.time() + WAITING_TTL_SECONDS, room["expires_at_epoch"])
                self._db.execute(
                    "UPDATE credentials SET active=0 WHERE room_id=? AND member_id=?",
                    (room_id, target),
                )
                event = "member.removed"
            elif action == "close":
                if room["owner_member_id"] != member_id:
                    raise AuthorityError(403, "only the room owner can close this room")
                attempt = room.get("attempt") or {}
                if attempt.get("phase") not in {None, "completed", "canceled", "failed"}:
                    attempt["phase"] = "canceled"
                    attempt["updated_at"] = _utc()
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

    def reconnect(self, room_id: str, reconnect_token: str, command_id: str) -> dict:
        with self._transaction():
            token_hash = _hash(reconnect_token)
            scope = f"reconnect:{room_id}:{token_hash[:16]}"
            if cached := self._secret_command_response(scope, command_id):
                return cached
            row = self._db.execute(
                "SELECT token_hash,reconnect_hash,member_id,active FROM credentials "
                "WHERE room_id=? AND (reconnect_hash=? OR "
                "(previous_reconnect_hash=? AND previous_reconnect_until>?))",
                (room_id, token_hash, token_hash, time.time()),
            ).fetchone()
            if row is None:
                raise AuthorityError(401, "reconnect credential is invalid")
            room = self._load(room_id)
            member = next(item for item in room["members"] if item["member_id"] == row["member_id"])
            if room["state"] in {"closed", "expired"} or member["online_state"] == "left":
                raise AuthorityError(410, "trade room is not active")
            deadline = member.get("reconnect_deadline")
            if (member["online_state"] == "offline" or
                    deadline and datetime.fromisoformat(
                        deadline.replace("Z", "+00:00")).timestamp() <= time.time()):
                raise AuthorityError(410, "reconnect deadline expired")
            if not row["active"]:
                raise AuthorityError(401, "reconnect credential is invalid")
            token, reconnect = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            self._db.execute(
                "UPDATE credentials SET token_hash=?,reconnect_hash=?,previous_reconnect_hash=?,"
                "previous_reconnect_until=? WHERE member_id=? AND room_id=?",
                (_hash(token), _hash(reconnect), row["reconnect_hash"],
                 time.time() + RECONNECT_SECONDS, row["member_id"], room_id),
            )
            member["online_state"] = "online"
            member["reconnect_deadline"] = None
            member["last_seen_epoch"] = time.time()
            room["room_version"] += 1
            self._event(room, "member.reconnected", member["member_id"])
            self._save(room)
            response = {"room": self._public(room, member["member_id"]), "member_token": token,
                        "reconnect_token": reconnect}
            self._remember_secret(scope, command_id, response)
            return response

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

    def fail_transport_attempt(self, room_id: str, attempt_id: str, code: str) -> bool:
        """Fail one active attempt after an authenticated RFU peer is lost."""
        with self._transaction():
            room = self._load(room_id)
            attempt = room.get("attempt") or {}
            if (room.get("state") in {"closed", "expired"} or
                    attempt.get("attempt_id") != attempt_id or
                    attempt.get("phase") in {None, "completed", "canceled", "failed"}):
                return False
            attempt["phase"] = "failed"
            attempt["recoverable_error"] = code
            attempt["updated_at"] = _utc()
            room["state"] = "ready_check"
            for member in room["members"]:
                if member["online_state"] != "left":
                    member["ready_state"] = "not_ready"
                    member["switch_room_role"] = None
            room["room_version"] += 1
            self._event(room, "attempt.failed", None, {"code": code})
            self._save(room)
            return True

    def fail_active_attempts(self, code: str) -> int:
        """Invalidate process-local transports after a relay process restart."""
        with self._lock:
            rows = self._db.execute("SELECT room_id,document FROM rooms").fetchall()
        failed = 0
        for row in rows:
            room = json.loads(row["document"])
            attempt = room.get("attempt") or {}
            attempt_id = attempt.get("attempt_id")
            if attempt_id and self.fail_transport_attempt(row["room_id"], attempt_id, code):
                failed += 1
        return failed

    def sweep_presence(self) -> None:
        now = time.time()
        with self._transaction():
            rows = self._db.execute("SELECT room_id,document FROM rooms").fetchall()
            for row in rows:
                room = self._load(row["room_id"])
                if room["state"] in {"closed", "expired"}:
                    continue
                changed = False
                for member in room["members"]:
                    if (member["online_state"] == "online" and
                            now - member.get("last_seen_epoch", now) > OFFLINE_DETECTION_SECONDS):
                        member["online_state"] = "reconnecting"
                        member["reconnect_deadline"] = _utc(now + RECONNECT_SECONDS)
                        changed = True
                        event = "member.reconnecting"
                    elif member["online_state"] == "reconnecting" and member.get("reconnect_deadline"):
                        deadline = datetime.fromisoformat(
                            member["reconnect_deadline"].replace("Z", "+00:00")).timestamp()
                        if deadline <= now:
                            member["online_state"] = "offline"
                            member["ready_state"] = "not_ready"
                            member["switch_room_role"] = None
                            self._db.execute(
                                "UPDATE credentials SET active=0 WHERE room_id=? AND member_id=?",
                                (room["room_id"], member["member_id"]),
                            )
                            attempt = room.get("attempt")
                            if attempt and attempt.get("phase") not in {"completed", "canceled", "failed"}:
                                attempt["phase"] = "failed"
                                attempt["recoverable_error"] = "member.reconnect_expired"
                                attempt["updated_at"] = _utc(now)
                                room["state"] = "ready_check"
                                for active_member in room["members"]:
                                    active_member["ready_state"] = "not_ready"
                                    active_member["switch_room_role"] = None
                            changed = True
                            event = "member.offline"
                        else:
                            continue
                    else:
                        continue
                    room["room_version"] += 1
                    self._event(room, event, member["member_id"])
                if changed:
                    self._save(room)
            self._db.execute("DELETE FROM commands WHERE created_at<?", (
                now - COMMAND_RETENTION_SECONDS,))
            self._db.execute(
                "DELETE FROM rooms WHERE expires_at<? AND json_extract(document, '$.state') IN ('closed','expired')",
                (now - AUTHORITY_RETENTION_SECONDS,),
            )
