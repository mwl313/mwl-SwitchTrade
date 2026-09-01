import tempfile
from pathlib import Path
import unittest
import uuid

from switchtrade.connection.coordinator import ConnectionCoordinator, RunMode
from switchtrade.connection.production_run import ProductionControlAdapter, ProductionLifecycle
from switchtrade.connection.service import RunControl
from switchtrade.connection.distributed_harness import DistributedCanceled


class RelayStub:
    def __init__(self):
        room_id = str(uuid.uuid4())
        self.snapshot = {
            "contract_version": "room-control.v1",
            "room_id": room_id,
            "room_code": "ABC123",
            "visibility": "private",
            "room_version": 2,
            "local_member_id": "local",
            "members": [
                {"member_id": "local", "seat": "member_a", "online_state": "online"},
                {"member_id": "peer", "seat": "member_b", "online_state": "online"},
            ],
        }
        self.created = 0

    def create_trade_room(self, _payload, _client_id, command_id=None):
        self.created += 1
        return {
            "room": dict(self.snapshot),
            "member_token": "m" * 32,
            "reconnect_token": "r" * 32,
        }

    def room(self, _room_id, _token):
        return dict(self.snapshot)


class ProductionLifecycleTests(unittest.TestCase):
    def test_checkpoint_stop_is_normal_distributed_cancellation(self):
        control = RunControl("run-1", lambda *_args: None)
        control.request_termination("stop")
        adapter = ProductionControlAdapter(control, lambda _action: None)
        with self.assertRaises(DistributedCanceled) as canceled:
            adapter.await_continue(
                "CREATE_SWITCH_ROOM", run_id="run-1", timeout=0.1)
        self.assertEqual(canceled.exception.gate, "CREATE_SWITCH_ROOM")

    def test_passed_gate_is_projected_with_factual_last_passed_gate(self):
        events = []
        control = RunControl("run-1", lambda event, value: events.append((event, value)))
        ProductionControlAdapter(control, lambda _action: None).gate_passed("C_RFU_ACTIVE")
        self.assertEqual(events, [("phase", {
            "phase": "running", "gate": "C_RFU_ACTIVE",
            "last_passed_gate": "C_RFU_ACTIVE", "peer_state": "paired",
        })])

    def test_c01_persists_private_authority_without_projecting_credentials(self):
        with tempfile.TemporaryDirectory(prefix="프로덕션-연결-") as temporary:
            root = Path(temporary)
            relay = RelayStub()
            events = []
            run_id = str(uuid.uuid4())
            control = RunControl(run_id, lambda event, value: events.append((event, value)))
            control.choose_role("a_room_joiner")
            with ConnectionCoordinator(root / "coordinator", "release-a") as coordinator:
                run = coordinator.start(
                    RunMode.NORMAL, run_id=run_id,
                    adapter_instance_id="USB\\RADIO", usb_id="0bda:818b")
                lifecycle = ProductionLifecycle(
                    coordinator=coordinator, relay=relay,
                    request={
                        "kind": "create", "switch_role": "a_room_joiner",
                        "name": "테스트 방", "authority_command_id": str(uuid.uuid4()),
                    },
                    run_control=control, root=root / "service",
                    distro="SwitchTrade", packaged_python="/python",
                    runtime_root="/opt/switchtrade", timeout=1,
                )
                lifecycle.establish({
                    "run_id": run_id, "run_root": root / "runs" / run_id,
                    "run": run, "adapter": object(), "p0a": {"status": "passed"},
                })

            self.assertEqual(relay.created, 1)
            authority = (root / "service" / "room-authority.private.json").read_text()
            self.assertIn("member_token", authority)
            projected = [value["room"] for event, value in events if event == "authority"]
            self.assertTrue(projected)
            self.assertNotIn("member_token", projected[-1])
            self.assertNotIn("reconnect_token", projected[-1])
            self.assertEqual(projected[-1]["room_code"], "ABC123")


if __name__ == "__main__":
    unittest.main()
