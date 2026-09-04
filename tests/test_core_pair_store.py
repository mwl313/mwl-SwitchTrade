from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from relay.pair_store import PairStore, PairStoreError
from switchtrade.core.contracts import EndpointCapabilities, EndpointKind, GenerationRole, RuntimeKind


def capabilities(role: GenerationRole) -> EndpointCapabilities:
    return EndpointCapabilities(EndpointKind.FAKE, RuntimeKind.IN_PROCESS, ("switchtrade.fake.v1",), (role,))


class PairStoreTests(unittest.TestCase):
    def test_create_join_is_one_time_and_token_bound(self) -> None:
        store = PairStore()
        host = store.create(capabilities(GenerationRole.ORIGIN))
        self.assertRegex(host.code or "", r"^\d{6}$")
        guest = store.join(host.code or "", capabilities(GenerationRole.MIRROR))
        self.assertNotIn(host.access_token, store._pairs[host.pair_id].token_hashes.values())
        self.assertNotIn(guest.access_token, store._pairs[host.pair_id].token_hashes.values())
        self.assertEqual(store.authenticate(host.pair_id, host.access_token).value, "host")
        self.assertEqual(store.authenticate(host.pair_id, guest.access_token).value, "guest")
        with self.assertRaises(PairStoreError):
            store.join(host.code or "", capabilities(GenerationRole.MIRROR))

    def test_status_never_projects_code_or_token(self) -> None:
        store = PairStore()
        host = store.create(capabilities(GenerationRole.ORIGIN))
        status = store.status(host.pair_id, host.access_token)
        self.assertNotIn("code", status)
        self.assertNotIn("access_token", status)
        with self.assertRaises(PairStoreError):
            store.authenticate(host.pair_id, "wrong")

    def test_code_collision_and_expiry_are_bounded(self) -> None:
        clock = Clock()
        store = PairStore(now=clock)
        with patch("relay.pair_store.secrets.randbelow", side_effect=[123456, 123456, 654321]):
            first = store.create(capabilities(GenerationRole.ORIGIN))
            second = store.create(capabilities(GenerationRole.ORIGIN))
        self.assertEqual(first.code, "123456")
        self.assertEqual(second.code, "654321")
        clock.advance(minutes=11)
        store.sweep()
        self.assertNotIn(first.code, store._codes)
        with self.assertRaisesRegex(PairStoreError, "PAIR_CODE_EXPIRED"):
            store.join(first.code or "", capabilities(GenerationRole.MIRROR))

    def test_join_is_atomic_and_tokens_are_seat_bound(self) -> None:
        store = PairStore()
        host = store.create(capabilities(GenerationRole.ORIGIN))
        with ThreadPoolExecutor(max_workers=2) as workers:
            outcomes = list(workers.map(lambda _: self._join(store, host.code or ""), range(2)))
        self.assertEqual(outcomes.count("guest"), 1)
        self.assertEqual(outcomes.count("PAIR_CODE_INVALID"), 1)
        with self.assertRaisesRegex(PairStoreError, "PAIR_AUTH_INVALID"):
            store.authenticate(host.pair_id, "wrong-token")

    def test_rate_limit_recovers_after_window(self) -> None:
        clock = Clock()
        store = PairStore(now=clock)
        for _ in range(8):
            store.create(capabilities(GenerationRole.ORIGIN), "client")
        with self.assertRaisesRegex(PairStoreError, "PAIR_RATE_LIMITED"):
            store.create(capabilities(GenerationRole.ORIGIN), "client")
        clock.advance(minutes=1, seconds=1)
        store.create(capabilities(GenerationRole.ORIGIN), "client")

    def test_reconnect_expiry_releases_capacity(self) -> None:
        clock = Clock()
        store = PairStore(max_pairs=1, now=clock)
        store.create(capabilities(GenerationRole.ORIGIN))
        with self.assertRaisesRegex(PairStoreError, "PAIR_CAPACITY"):
            store.create(capabilities(GenerationRole.ORIGIN))
        clock.advance(hours=1, seconds=1)
        store.sweep()
        self.assertFalse(store._pairs)
        store.create(capabilities(GenerationRole.ORIGIN))

    @staticmethod
    def _join(store: PairStore, code: str) -> str:
        try:
            return store.join(code, capabilities(GenerationRole.MIRROR)).seat.value
        except PairStoreError as exc:
            return exc.code


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self, _: object) -> datetime:
        return self.value

    def advance(self, **delta: int) -> None:
        self.value += timedelta(**delta)


if __name__ == "__main__":
    unittest.main()
