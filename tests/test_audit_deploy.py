"""The deploy settings let a request in flight finish when Railway redeploys. Offline."""

from __future__ import annotations

import json
import re
from pathlib import Path

from quant_trade.audit.settings import DEFAULT_AUDIT_QUEUE_SECONDS
from quant_trade.audit.web import PDF_WAIT_SECONDS

ROOT = Path(__file__).resolve().parents[1]


def test_the_old_deployment_gets_time_to_finish_its_requests() -> None:
    # Every merge redeploys; Railway's default is SIGKILL right after SIGTERM,
    # which cut off the audits and PDFs of whoever was waiting on one.
    deploy = json.loads((ROOT / "railway.json").read_text())["deploy"]
    draining = deploy["drainingSeconds"]
    # railway.schema.json takes a number; a string (as a docs example shows) is refused.
    assert isinstance(draining, int)
    assert draining >= PDF_WAIT_SECONDS + 30
    assert draining >= DEFAULT_AUDIT_QUEUE_SECONDS + 30


def test_the_server_itself_receives_the_sigterm() -> None:
    # Under `sh -c "cmd"` the shell is PID 1 and never passes SIGTERM on.
    cmd = next(
        line
        for line in (ROOT / "Dockerfile.web").read_text().splitlines()
        if line.startswith("CMD ")
    )
    assert re.search(r'"exec quant-trade audit serve ', cmd), cmd
