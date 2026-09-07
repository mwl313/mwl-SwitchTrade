import logging
from types import SimpleNamespace

from switchtrade.connection.stage_session import StageSession
from switchtrade.core_cli import _configure_logging


def test_opt_in_log_contains_gate_cleanup_but_no_private_stage_payload(tmp_path):
    args = SimpleNamespace(verbose=False, log_dir=tmp_path)
    _configure_logging(args)
    stage = SimpleNamespace(run_id="test-run")
    session = StageSession(stage)
    session.report = {
        "failure": {"code": "A_KEYS_INVALID", "gate": "A0", "message": "SECRET_MESSAGE"},
        "keys": "SECRET_KEY", "advertisement": "SECRET_ADVERTISEMENT", "mac": "SECRET_MAC",
        "cleanup": {"radio_quiescent": False, "resources": {"join.vif.2": "unknown"},
                    "private_path": "SECRET_PATH"},
    }
    try:
        session._log_report()
        logging.getLogger("switchtrade.core_cli").info("ordinary CLI status")
        text = (tmp_path / "switchtrade-core.log").read_text(encoding="utf-8")
        assert "A_KEYS_INVALID" in text and "join.vif.2" in text and "ordinary CLI status" in text
        assert "SECRET" not in text
    finally:
        _configure_logging(SimpleNamespace(verbose=False, log_dir=None))
