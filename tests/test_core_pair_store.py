from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
