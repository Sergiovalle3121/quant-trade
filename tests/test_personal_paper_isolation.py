"""The public audit service never imports the private paper simulator."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

SRC = Path(__file__).resolve().parents[1] / "src"
PRIVATE = "quant_trade.personal_paper"

_SERVE_PROBE = """
import json, sys
import uvicorn
served = []
uvicorn.run = lambda app, **kwargs: served.append(type(app).__name__)
from typer.testing import CliRunner
from quant_trade.cli import app
runner = CliRunner()
results = [
    runner.invoke(app, ["audit", "--help"]),
    runner.invoke(app, ["audit", "serve", "--host", "127.0.0.1", "--port", "8765"]),
]
from quant_trade.audit.web import create_app
created = type(create_app()).__name__
private = [m for m in sys.modules if m == sys.argv[1] or m.startswith(sys.argv[1] + ".")]
print(json.dumps({
    "exit_codes": [result.exit_code for result in results],
    "output": results[-1].output,
    "served": served,
    "created": created,
    "private": sorted(private),
}))
"""

_GROUP_PROBE = """
import json, sys
from typer.testing import CliRunner
from quant_trade.cli import app
before = sorted(m for m in sys.modules if m.startswith(sys.argv[1]))
result = CliRunner().invoke(app, ["personal-paper", "status", "--database", "absent.db"])
print(json.dumps({
    "before": before,
    "exit_code": result.exit_code,
    "error": repr(result.exception),
    "engine": sys.argv[1] + ".engine" in sys.modules,
}))
"""


def _private(name: str) -> bool:
    return name == PRIVATE or name.startswith(PRIVATE + ".")


def _run(code: str, *args: str, cwd: Path) -> dict:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("STRIPE_", "AUDIT_", "RESEND_", "DATABASE_URL"))
    }
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(SRC), env.get("PYTHONPATH")]))
    env["DATABASE_URL"] = f"sqlite:///{(cwd / 'audit.db').as_posix()}"
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, "-B", "-c", code, *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_audit_serve_and_web_app_leave_the_private_simulator_unimported(tmp_path: Path):
    pytest.importorskip("fastapi")
    pytest.importorskip("uvicorn")
    probe = _run(_SERVE_PROBE, PRIVATE, cwd=tmp_path)
    assert probe["exit_codes"] == [0, 0], probe["output"]
    assert probe["served"] == ["FastAPI"] and probe["created"] == "FastAPI"
    assert probe["private"] == []


def test_personal_paper_group_resolves_lazily_through_the_main_cli(tmp_path: Path):
    probe = _run(_GROUP_PROBE, PRIVATE, cwd=tmp_path)
    assert probe["before"] == []
    assert probe["exit_code"] != 0 and "paper database does not exist" in probe["error"]
    assert probe["engine"] is True
    assert not (tmp_path / "absent.db").exists()


def test_main_cli_help_keeps_personal_paper_after_audit():
    import typer

    from quant_trade.cli import app

    result = CliRunner().invoke(app, ["personal-paper", "--help"])
    assert result.exit_code == 0, result.output
    for command in ("run", "worker", "status", "pause", "resume", "export", "backup"):
        assert command in result.output
    # Order comes from the group itself: Rich adds ANSI styling to rendered help
    # when GITHUB_ACTIONS or FORCE_COLOR is set, so the text is not compared.
    group = typer.main.get_command(app)
    names = group.list_commands(typer.Context(group))
    assert names.count("personal-paper") == 1
    assert names.index("personal-paper") == names.index("audit") + 1
    assert names.index("personal-paper") < names.index("allocation")
    root = CliRunner().invoke(app, ["--help"])
    assert root.exit_code == 0, root.output
    assert "personal-paper" in root.output


def test_python_module_entry_point_still_runs(tmp_path: Path):
    completed = subprocess.run(
        [sys.executable, "-B", "-m", PRIVATE, "--help"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(SRC), "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "worker" in completed.stdout and "pause" in completed.stdout


def _imports(source: str, package: list[str]) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = package[: len(package) - node.level + 1] if node.level else []
            module = ".".join([*base, *([node.module] if node.module else [])])
            found.add(module)
            found.update(f"{module}.{alias.name}" for alias in node.names)
        elif (
            isinstance(node, ast.Call)
            and (
                (isinstance(node.func, ast.Name) and node.func.id == "__import__")
                or (isinstance(node.func, ast.Attribute) and node.func.attr == "import_module")
            )
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            found.add(node.args[0].value)
    return found


def _module_imports(path: Path) -> set[str]:
    package = list(path.relative_to(SRC).with_suffix("").parts[:-1])
    return _imports(path.read_text(encoding="utf-8"), package)


def test_audit_package_source_never_imports_the_private_simulator():
    files = sorted((SRC / "quant_trade" / "audit").rglob("*.py"))
    assert len(files) > 50
    assert "quant_trade.audit.settings" in _module_imports(SRC / "quant_trade/audit/web.py")
    offenders = {
        str(path.relative_to(SRC)): sorted(filter(_private, _module_imports(path)))
        for path in files
    }
    assert {path: names for path, names in offenders.items() if names} == {}


def test_import_scanner_resolves_relative_and_dynamic_private_imports():
    source = "\n".join(
        [
            "from .. import personal_paper",
            "from ..personal_paper import engine",
            "import importlib",
            "importlib.import_module('quant_trade.personal_paper.store')",
            "__import__('quant_trade.personal_paper.worker')",
        ]
    )
    assert set(filter(_private, _imports(source, ["quant_trade", "audit"]))) == {
        "quant_trade.personal_paper",
        "quant_trade.personal_paper.engine",
        "quant_trade.personal_paper.store",
        "quant_trade.personal_paper.worker",
    }
