"""The deploy settings let a request in flight finish when Railway redeploys. Offline."""

from __future__ import annotations

import re
from pathlib import Path

from quant_trade.audit.settings import DEFAULT_AUDIT_QUEUE_SECONDS
from quant_trade.audit.web import PDF_WAIT_SECONDS

ROOT = Path(__file__).resolve().parents[1]


def test_the_old_deployment_gets_time_to_finish_its_requests() -> None:
    # Every merge redeploys; Railway's default is SIGKILL right after SIGTERM,
    # which cut off the audits and PDFs of whoever was waiting on one. The
    # draining time is a setting of the service on Railway, so the number the
    # operator is told to set is the one checked here.
    guide = (ROOT / "docs" / "AUDIT_SAAS.md").read_text(encoding="utf-8")
    told = re.search(r"Draining time to (\d+) s", guide)
    assert told, "docs/AUDIT_SAAS.md no longer says which draining time to set"
    draining = int(told.group(1))
    assert f"RAILWAY_DEPLOYMENT_DRAINING_SECONDS={draining}" in guide
    assert draining >= PDF_WAIT_SECONDS + 30
    assert draining >= DEFAULT_AUDIT_QUEUE_SECONDS + 30


def test_the_service_is_not_configured_from_a_file_railway_stopped_reading() -> None:
    # Railway deprecated config as code: the service's own settings name the
    # Dockerfile, the health check and the restart policy.
    assert not (ROOT / "railway.json").exists()
    assert not (ROOT / "railway.toml").exists()
    guide = (ROOT / "docs" / "AUDIT_SAAS.md").read_text(encoding="utf-8")
    assert "Dockerfile path `Dockerfile.web`" in guide
    assert "healthcheck path `/ready`" in guide


def test_the_server_itself_receives_the_sigterm() -> None:
    # Under `sh -c "cmd"` the shell is PID 1 and never passes SIGTERM on.
    cmd = next(
        line
        for line in (ROOT / "Dockerfile.web").read_text().splitlines()
        if line.startswith("CMD ")
    )
    assert re.search(r'"exec quant-trade audit serve ', cmd), cmd
