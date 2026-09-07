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
        self.assertEqual(outcomes.count("PAIR_CODE_CONSUMED"), 1)
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

    def test_rate_table_caps_new_identities_without_evicting_live_budgets(self):
        clock = Clock()
        store = PairStore(now=clock)
        with patch("relay.pair_store.MAX_RATE_BUCKETS", 3):
            for _ in range(8):
                store.create(capabilities(GenerationRole.ORIGIN), "existing")
            for index in range(2):
                store.create(capabilities(GenerationRole.ORIGIN), f"other-{index}")
            for index in range(100):
                with self.assertRaisesRegex(PairStoreError, "PAIR_RATE_LIMITED"):
                    store.create(capabilities(GenerationRole.ORIGIN), f"new-{index}")
            self.assertEqual(len(store._limits), 3)
            with self.assertRaisesRegex(PairStoreError, "PAIR_RATE_LIMITED"):
                store.create(capabilities(GenerationRole.ORIGIN), "existing")
            clock.advance(minutes=1)
            store.create(capabilities(GenerationRole.ORIGIN), "new-after-expiry")
            self.assertEqual(set(store._limits), {("create", "new-after-expiry")})

    def test_sweep_reclaims_expired_join_and_guess_history(self):
        clock = Clock()
        store = PairStore(now=clock)
        for index in range(100):
            with self.assertRaisesRegex(PairStoreError, "PAIR_CODE_INVALID"):
                store.join("invalid", capabilities(GenerationRole.MIRROR), str(index))
        self.assertEqual(len(store._limits), 200)
        clock.advance(minutes=1)
        store.sweep()
        self.assertFalse(store._limits)

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

    def test_old_code_expiry_does_not_remove_a_reused_code_owner(self) -> None:
        clock = Clock()
        store = PairStore(now=clock)
        with patch("relay.pair_store.secrets.randbelow", side_effect=[381742, 381742]):
            old = store.create(capabilities(GenerationRole.ORIGIN))
            store.join(old.code or "", capabilities(GenerationRole.MIRROR))
            clock.advance(minutes=1)
            current = store.create(capabilities(GenerationRole.ORIGIN))
        clock.advance(minutes=9, seconds=1)
        store.sweep()
        self.assertEqual(store._codes.get(current.code or ""), current.pair_id)
        self.assertEqual(
            store.join(current.code or "", capabilities(GenerationRole.MIRROR)).pair_id,
            current.pair_id,
        )

    def test_connected_pair_survives_reconnect_lease_but_cannot_readmit(self):
        clock = Clock()
        store = PairStore(now=clock)
        host = store.create(capabilities(GenerationRole.ORIGIN))
        store.attach(host.pair_id, host.access_token, "stream-1")
        clock.advance(hours=2)
        store.sweep()
        self.assertIn(host.pair_id, store._pairs)
        with self.assertRaisesRegex(PairStoreError, "PAIR_AUTH_INVALID"):
            store.attach(host.pair_id, host.access_token, "stream-2")
        store.detach(host.pair_id, "stream-1")
        self.assertNotIn(host.pair_id, store._pairs)

    def test_consumed_invite_is_explicit_but_established_pair_is_independent(self):
        clock = Clock()
        store = PairStore(now=clock)
        host = store.create(capabilities(GenerationRole.ORIGIN))
        guest = store.join(host.code, capabilities(GenerationRole.MIRROR))
        with self.assertRaisesRegex(PairStoreError, "PAIR_CODE_CONSUMED"):
            store.join(host.code, capabilities(GenerationRole.MIRROR))
        clock.advance(minutes=11)
        self.assertEqual(store.authenticate(host.pair_id, guest.access_token).value, "guest")
        with self.assertRaisesRegex(PairStoreError, "PAIR_CODE_EXPIRED"):
            store.join(host.code, capabilities(GenerationRole.MIRROR))

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
