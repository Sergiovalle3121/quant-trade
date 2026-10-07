"""The PowerShell wrapper keeps logging and the worker exit code after stderr."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "personal-paper-worker.ps1"


def _shells() -> list[str]:
    names = ["powershell.exe", "pwsh"] if os.name == "nt" else ["pwsh"]
    return [path for name in names if (path := shutil.which(name))]


def _fake_python(directory: Path) -> Path:
    """A native command that warns on stderr, keeps writing, then fails with 3."""
    if os.name == "nt":
        fake = directory / "fake-python.cmd"
        fake.write_text(
            "@echo off\r\n"
            "echo synthetic worker started\r\n"
            "echo synthetic provider warning 1>&2\r\n"
            "echo synthetic worker continued after warning\r\n"
            "echo %*\r\n"
            "exit /b 3\r\n",
            encoding="ascii",
        )
    else:
        fake = directory / "fake-python"
        fake.write_text(
            "#!/bin/sh\n"
            "echo synthetic worker started\n"
            "echo synthetic provider warning 1>&2\n"
            "echo synthetic worker continued after warning\n"
            'echo "$@"\n'
            "exit 3\n",
            encoding="ascii",
        )
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    return fake


@pytest.mark.parametrize("shell", _shells() or [None])
def test_stderr_from_the_worker_does_not_abort_the_wrapper(tmp_path: Path, shell: str | None):
    if shell is None:
        pytest.skip("no PowerShell available")
    repository, state = tmp_path / "repo", tmp_path / "state"
    repository.mkdir()
    completed = subprocess.run(
        [
            shell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-PythonPath",
            str(_fake_python(tmp_path)),
            "-RepositoryPath",
            str(repository),
            "-StatePath",
            str(state),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 3, completed.stdout + completed.stderr
    logs = list(state.glob("worker-*.log"))
    assert len(logs) == 1
    log = logs[0].read_text(encoding="utf-8-sig")
    for line in (
        "synthetic worker started",
        "synthetic provider warning",
        "synthetic worker continued after warning",
        "-m quant_trade.personal_paper worker --config",
    ):
        assert line in log
    assert "NativeCommandError" not in log and "CategoryInfo" not in log


def test_wrapper_relaxes_error_preference_only_around_the_native_call():
    lines = SCRIPT.read_text(encoding="utf-8").splitlines()
    call = next(i for i, line in enumerate(lines) if line.startswith("& $taskPython"))
    assert lines[0] == "param(" and '$ErrorActionPreference = "Stop"' in lines[:10]
    assert lines[call - 1] == '$ErrorActionPreference = "Continue"'
    assert '$ErrorActionPreference = "Stop"' in lines[call + 1 :]
    assert lines[-1] == "exit $taskExitCode"
