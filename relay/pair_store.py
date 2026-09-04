"""In-memory, credential-bound two-seat pair store for the new Core relay."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import secrets

from switchtrade.core.contracts import EndpointCapabilities, PairCredentials, PairSeat


class PairStoreError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass
class PairRecord:
    pair_id: str
    code: str
    code_expires_at: datetime
    reconnect_expires_at: datetime
    host: EndpointCapabilities
    tokens: dict[str, PairSeat]
    guest: EndpointCapabilities | None = None


class PairStore:
    def __init__(self, *, max_pairs: int = 128, now=datetime.now) -> None:
        self._max_pairs, self._now = max_pairs, now
        self._pairs: dict[str, PairRecord] = {}
        self._codes: dict[str, str] = {}

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def _time(self) -> datetime:
        return self._now(UTC)

    def sweep(self) -> None:
        now = self._time()
        for pair_id, record in tuple(self._pairs.items()):
            if record.reconnect_expires_at <= now:
                self._pairs.pop(pair_id)
                self._codes.pop(record.code, None)

    def create(self, capabilities: EndpointCapabilities) -> PairCredentials:
        self.sweep()
        if len(self._pairs) >= self._max_pairs:
            raise PairStoreError("PAIR_CAPACITY")
        code = self._new_code()
        pair_id, token = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
        now = self._time()
        record = PairRecord(pair_id, code, now + timedelta(minutes=10), now + timedelta(hours=1), capabilities, {self._hash(token): PairSeat.HOST})
        self._pairs[pair_id], self._codes[code] = record, pair_id
        return PairCredentials(pair_id, PairSeat.HOST, token, record.reconnect_expires_at.isoformat(), code)

    def join(self, code: str, capabilities: EndpointCapabilities) -> PairCredentials:
        self.sweep()
        if not code.isdigit() or len(code) != 6 or code not in self._codes:
            raise PairStoreError("PAIR_CODE_INVALID")
        record = self._pairs[self._codes[code]]
        if record.code_expires_at <= self._time():
            self._codes.pop(code, None)
            raise PairStoreError("PAIR_CODE_EXPIRED")
        if record.guest is not None:
            raise PairStoreError("PAIR_CODE_CONSUMED")
        shared = set(record.host.protocols) & set(capabilities.protocols)
        if not shared:
            raise PairStoreError("PROTOCOL_INCOMPATIBLE")
        token = secrets.token_urlsafe(32)
        record.tokens[self._hash(token)] = PairSeat.GUEST
        record.guest = capabilities
        self._codes.pop(code, None)
        return PairCredentials(record.pair_id, PairSeat.GUEST, token, record.reconnect_expires_at.isoformat())

    def authenticate(self, pair_id: str, token: str) -> PairSeat:
        self.sweep()
        record = self._pairs.get(pair_id)
        if record is None or self._hash(token) not in record.tokens:
            raise PairStoreError("PAIR_AUTH_INVALID")
        return record.tokens[self._hash(token)]

    def status(self, pair_id: str, token: str) -> dict[str, object]:
        seat = self.authenticate(pair_id, token)
        record = self._pairs[pair_id]
        return {"pair_id": pair_id, "seat": seat, "guest_joined": record.guest is not None, "negotiated_protocols": sorted(set(record.host.protocols) & set(record.guest.protocols)) if record.guest else []}

    def _new_code(self) -> str:
        for _ in range(100):
            code = f"{secrets.randbelow(1_000_000):06d}"
            if code not in self._codes:
                return code
        raise PairStoreError("PAIR_CODE_EXHAUSTED")
