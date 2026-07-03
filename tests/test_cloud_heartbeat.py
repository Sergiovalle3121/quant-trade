from datetime import UTC, datetime, timedelta

from quant_trade.cloud.heartbeat import Heartbeat, is_stale, read_heartbeat, write_heartbeat
from quant_trade.cloud.storage import LocalStorageBackend


def hb(ts=None):
    return Heartbeat(
        deployment_name="d",
        job_name="j",
        run_id="r",
        status="ok",
        started_at_utc="t",
        last_update_utc=ts or datetime.now(UTC).isoformat(),
        mode="dry_run",
        broker_provider="simulated",
        paper_submission_enabled=False,
        kill_switch_active=False,
    )


def test_heartbeat_local(tmp_path):
    p = str(tmp_path / "h.json")
    write_heartbeat(LocalStorageBackend(), p, hb())
    assert read_heartbeat(LocalStorageBackend(), p).run_id == "r"


def test_stale():
    assert is_stale(hb((datetime.now(UTC) - timedelta(hours=2)).isoformat()), 30)


def test_bad_stale():
    assert is_stale(hb("bad"), 30)
