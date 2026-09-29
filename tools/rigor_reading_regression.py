"""Proof that a change to how files are READ leaves every other file alone.

The audit is run on every file the repository holds (the importer
fixtures, the example upload, every synthetic generator of
``tests/audit_fixtures.py`` with its default parameters), on the new reading
cases (day/month/year dates, ``;`` with a decimal point, fewer than three
returns) and, with ``--extra``, on the files of a local folder. Each case
becomes one record: the class, the period, the observations, every headline
number with its evidence tag and the whole result as JSON.

Two commands::

    # One snapshot, with whichever ``quant_trade`` is first on PYTHONPATH.
    python tools/rigor_reading_regression.py snapshot --out snapshot.json

    # The same cases under two source trees, compared field by field.
    python tools/rigor_reading_regression.py compare --base-src D:/quant-trade/src

``compare`` runs ``snapshot`` twice in a subprocess, once with ``--base-src``
first on PYTHONPATH and once with this checkout's ``src``, so neither run can
import the other's code. It exits 1 when a case outside ``EXPECTED_TO_CHANGE``
differs in anything but the notes that state how its dates were read.

Nothing here touches the network, and no client file is written anywhere:
the snapshots hold figures, not the uploaded rows.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
BOOTSTRAP_SAMPLES = 200

#: Cases made to change: files that were read wrongly before.
EXPECTED_TO_CHANGE = ("new/",)

#: The only fields a history with fewer than three returns may change in:
#: its Sharpe and Sortino, a measured zero before and NOT_MEASURED now.
SHORT_HISTORY_FIELDS = (".headline.performance.sharpe", ".headline.performance.sortino",
                        ".result.performance.sharpe.", ".result.performance.sortino.")  # fmt: skip

#: Notes that only state how the file's dates were read.
DATE_NOTE = "dates read as "

#: The customer's own naming of the hand-made list's columns.
COLUMNS = {
    "entry_time": "abertura",
    "exit_time": "fechamento",
    "quantity": "qtd",
    "entry_price": "preco_in",
    "exit_price": "preco_out",
    "side": "lado",
    "symbol": "ativo",
}


def _fixtures_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "rigor_audit_fixtures", ROOT / "tests" / "audit_fixtures.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def day_month_curve(frame: Any, style: str) -> bytes:
    """``frame`` (timestamp, equity) written the way a spreadsheet set to
    Spanish or Portuguese writes it. ``style`` is one of ``/``, ``.``, ``-``,
    ``time``, ``fecha`` (``fecha;equity`` with a decimal comma), ``us``
    (month first) or ``iso``."""
    stamps = frame["timestamp"]
    values = [f"{value:.2f}" for value in frame["equity"]]
    if style == "fecha":
        rows = [
            f"{stamp:%d/%m/%Y};{value.replace('.', ',')}"
            for stamp, value in zip(stamps, values, strict=True)
        ]
        return ("fecha;equity\n" + "\n".join(rows) + "\n").encode("utf-8")
    formats = {
        "/": "%d/%m/%Y",
        ".": "%d.%m.%Y",
        "-": "%d-%m-%Y",
        "time": "%d/%m/%Y %H:%M:%S",
        "us": "%m/%d/%Y",
        "iso": "%Y-%m-%d",
    }
    rows = [
        f"{stamp.strftime(formats[style])},{value}"
        for stamp, value in zip(stamps, values, strict=True)
    ]
    return ("date,equity\n" + "\n".join(rows) + "\n").encode("utf-8")


def day_month_trades(frame: Any, style: str = "%d/%m/%Y %H:%M") -> bytes:
    """A trades frame with its two time columns written day first."""
    out = frame.copy()
    for column in ("entry_time", "exit_time"):
        out[column] = [stamp.strftime(style) for stamp in out[column]]
    return out.to_csv(index=False).encode("utf-8")


def generic_trades(delimiter: str, decimal: str, *, thousands: bool = False) -> bytes:
    """A hand-made list of closed trades with Portuguese column names, as the
    customer of the finding uploaded it."""
    header = ["abertura", "fechamento", "qtd", "preco_in", "preco_out", "lado", "ativo"]
    lines = [delimiter.join(header)]
    for index in range(40):
        day = 2 + index * 7
        month = 1 + day // 28
        opened = f"2024-{month:02d}-{1 + day % 28:02d} 10:00:00"
        closed = f"2024-{month:02d}-{1 + day % 28:02d} 15:30:00"
        price_in = 109.48 + index * 0.37
        move = (1.85 if index % 3 else -2.4) + (index % 5) * 0.11
        price_out = price_in + move
        if thousands:
            price_in, price_out = price_in + 1200.0, price_out + 1200.0
        cells = [opened, closed, "10"]
        for price in (price_in, price_out):
            text = f"{price:,.2f}" if thousands else f"{price:.2f}"
            if decimal == ",":
                text = text.replace(",", "\u00a7").replace(".", ",").replace("\u00a7", ".")
            if delimiter in text:
                text = f'"{text}"'
            cells.append(text)
        cells += ["compra", "PETR4"]
        lines.append(delimiter.join(cells))
    return ("\n".join(lines) + "\n").encode("utf-8")


def short_curve(rows: int) -> bytes:
    values = [10_000.0, 10_150.0, 10_090.0, 10_240.0][:rows]
    lines = [f"2024-0{index + 1}-15,{value:.2f}" for index, value in enumerate(values)]
    return ("date,equity\n" + "\n".join(lines) + "\n").encode("utf-8")


def cases(extra: Path | None) -> list[dict[str, Any]]:
    """Every case as ``{"name", "files": {role: bytes}, "declared": {...}}``."""
    fx = _fixtures_module()
    out: list[dict[str, Any]] = []

    def add(name: str, declared: dict[str, Any] | None = None, **files: Any) -> None:
        out.append({"name": name, "files": files, "declared": declared or {}})

    imports = ROOT / "tests" / "fixtures" / "audit_imports"
    for path in sorted(imports.iterdir()):
        if path.name == "mt5_optimization.xml":
            continue
        add(f"fixtures/{path.name}", report_bytes=path.read_bytes(), report_filename=path.name)
    add(
        "fixtures/mt5_tester.html+mt5_optimization.xml",
        report_bytes=(imports / "mt5_tester.html").read_bytes(),
        report_filename="mt5_tester.html",
        optimization_bytes=(imports / "mt5_optimization.xml").read_bytes(),
    )
    examples = ROOT / "examples" / "audit"
    equity = (examples / "sample_equity.csv").read_bytes()
    trades = (examples / "sample_trades.csv").read_bytes()
    add("examples/sample_equity.csv", equity_bytes=equity)
    add("examples/sample_equity.csv+sample_trades.csv", equity_bytes=equity, trades_bytes=trades)
    add(
        "examples/sample_equity.csv+trades declared",
        {"trials": 1, "cost_bps_per_side": 1.0, "oos_start": "2023-01-01"},
        equity_bytes=equity,
        trades_bytes=trades,
    )

    drift = fx.positive_drift()
    winner, matrix = fx.best_of_n_walks()
    add("synthetic/positive_drift", equity_bytes=fx.csv_bytes(drift))
    add("synthetic/positive_drift;semicolon", equity_bytes=fx.csv_bytes(drift, sep=";"))
    add("synthetic/returns_frame", equity_bytes=fx.csv_bytes(fx.returns_frame()))
    add(
        "synthetic/best_of_n_walks+variants",
        {"trials": 100, "cost_bps_per_side": 5.0},
        equity_bytes=fx.csv_bytes(winner),
        variants_bytes=fx.variants_bytes(matrix),
    )
    add("synthetic/stale_marks", equity_bytes=fx.csv_bytes(fx.stale_marks()))
    add("synthetic/spiked", equity_bytes=fx.csv_bytes(fx.spiked()))
    add(
        "synthetic/positive_drift+trades_frame",
        equity_bytes=fx.csv_bytes(drift),
        trades_bytes=fx.csv_bytes(fx.trades_frame()),
    )
    add(
        "synthetic/positive_drift+trades_frame short",
        equity_bytes=fx.csv_bytes(drift),
        trades_bytes=fx.csv_bytes(fx.trades_frame(side="short")),
    )
    add(
        "synthetic/positive_drift+trades_following",
        {"trials": 1, "cost_bps_per_side": 1.0},
        equity_bytes=fx.csv_bytes(drift),
        trades_bytes=fx.csv_bytes(fx.trades_following(drift)),
    )
    add(
        "synthetic/positive_drift+benchmark_lower_drift",
        equity_bytes=fx.csv_bytes(drift),
        benchmark_bytes=fx.csv_bytes(fx.benchmark_lower_drift()),
    )
    add(
        "synthetic/mt5_report",
        report_bytes=fx.synthetic_mt5_report(),
        report_filename="synthetic.html",
    )
    add(
        "synthetic/mt5_report+optimization",
        report_bytes=fx.synthetic_mt5_report(),
        report_filename="synthetic.html",
        optimization_bytes=fx.synthetic_mt5_optimization(),
    )
    add(
        "synthetic/mt5_report tampered fixture",
        report_bytes=fx.tampered_mt5_tester_bytes((imports / "mt5_tester.html").read_bytes()),
        report_filename="mt5_tester.html",
    )

    def listed(name: str, data: bytes, balance: float = 100_000.0) -> None:
        add(
            name,
            {"initial_balance": balance},
            report_bytes=data,
            report_filename="operacoes.csv",
            report_columns=COLUMNS,
        )

    # Files already read correctly that sit next to the new rules.
    add("kept/curve month first", equity_bytes=day_month_curve(drift, "us"))
    add("kept/curve iso", equity_bytes=day_month_curve(drift, "iso"))
    listed("kept/trades comma decimal point", generic_trades(",", "."))
    listed("kept/trades semicolon decimal comma", generic_trades(";", ","))
    listed(
        "kept/trades semicolon thousands 1.234,56",
        generic_trades(";", ",", thousands=True),
        1_000_000.0,
    )
    listed(
        "kept/trades comma thousands 1,234.56",
        generic_trades(",", ".", thousands=True),
        1_000_000.0,
    )

    # The new reading cases: these are the ones meant to change.
    styles = {
        "/": "slash",
        ".": "dot",
        "-": "dash",
        "time": "with time",
        "fecha": "fecha semicolon decimal comma",
    }
    for style, label in styles.items():
        add(f"new/curve day first {label}", equity_bytes=day_month_curve(drift, style))
    add(
        "new/trades day first beside iso curve",
        {"trials": 1, "cost_bps_per_side": 1.0},
        equity_bytes=fx.csv_bytes(drift),
        trades_bytes=day_month_trades(fx.trades_following(drift)),
    )
    listed("new/trades semicolon decimal point", generic_trades(";", "."))
    listed(
        "new/trades semicolon thousands 1,234.56",
        generic_trades(";", ".", thousands=True),
        1_000_000.0,
    )
    months = [(year, month) for year in (2022, 2023) for month in range(1, 13)]
    monthly = "".join(
        f"01/{month:02d}/{year},{10_000 + 35 * index + (index % 4) * 60:.2f}\n"
        for index, (year, month) in enumerate(months)
    )
    add(
        "new/curve monthly on the 1st, settled by order",
        equity_bytes=("date,equity\n" + monthly).encode("utf-8"),
    )
    add(
        "new/curve dates readable both ways",
        equity_bytes=(
            b"date,equity\n01/02/2024,10000\n01/03/2024,10100\n01/04/2024,10050\n01/05/2024,10200\n"
        ),
    )
    add(
        "new/curve mixing both orders",
        equity_bytes=b"date,equity\n13/01/2024,10000\n01/14/2024,10100\n01/15/2024,10050\n",
    )
    # 109.48 becomes 109.148: three digits after the only mark.
    listed(
        "new/trades semicolon numbers readable both ways",
        generic_trades(";", ".").replace(b".", b".1"),
    )
    add("new/curve with two returns", equity_bytes=short_curve(3))
    add("new/curve with one return", equity_bytes=short_curve(2))

    if extra is not None and extra.is_dir():
        for path in sorted(extra.iterdir()):
            if not path.is_file() or path.stat().st_size > 6_000_000:
                continue
            data = path.read_bytes()
            if path.suffix.lower() == ".xml":
                continue
            add(f"extra/{path.name} as report", report_bytes=data, report_filename=path.name)
            if path.suffix.lower() == ".csv":
                add(f"extra/{path.name} as curve", equity_bytes=data)
    return out


def _figure(value: Any) -> Any:
    """An evidence dict as ``value [TAG]``; anything else unchanged."""
    if isinstance(value, dict) and "evidence" in value:
        shown = value.get("value")
        if isinstance(shown, float):
            shown = round(shown, 10)
        reason = value.get("note") or ""
        return f"{shown} [{value['evidence']}]" + (f" ({reason})" if shown is None else "")
    return value


def run_case(case: dict[str, Any]) -> dict[str, Any]:
    """One case under the ``quant_trade`` that is importable right now."""
    from quant_trade.audit.engine import run_audit
    from quant_trade.audit.schema import DeclaredMetadata, ParseError, build_inputs

    files = dict(case["files"])
    equity = files.pop("equity_bytes", None)
    try:
        inputs = build_inputs(equity, DeclaredMetadata(**case["declared"]), now=NOW, **files)
        result = run_audit(
            inputs,
            now=NOW,
            audit_id="regression",
            bootstrap_samples=BOOTSTRAP_SAMPLES,
            source_commit_sha="regression",
        )
    except ParseError as exc:
        return {
            "name": case["name"],
            "outcome": "refused",
            "headline": {"code": getattr(exc, "code", "parse"), "message": str(exc)},
            "result": None,
        }
    data = json.loads(result.model_dump_json())
    stamps = inputs.equity.frame["timestamp"]
    stats = data.get("trade_stats") or {}
    headline = {
        "class": data["verdict"]["overall"],
        "first": stamps.iloc[0].isoformat(),
        "last": stamps.iloc[-1].isoformat(),
        "observations": int(len(stamps)),
        "dimensions": {d["name"]: d["status"] for d in data["verdict"]["dimensions"]},
        "red_flags": sorted(f"{f.get('code')}:{f.get('severity')}" for f in data["red_flags"]),
        "performance": {key: _figure(value) for key, value in data["performance"].items()},
        "psr": _figure((data["significance"] or {}).get("psr")),
        "dsr": _figure((data["multiplicity"] or {}).get("dsr")),
        "trades": {
            key: _figure(stats.get(key))
            for key in ("trade_count", "win_rate", "profit_factor", "gross_profit", "net_profit")
            if key in stats
        },
        "warnings": list(inputs.warnings),
    }
    return {"name": case["name"], "outcome": "audited", "headline": headline, "result": data}


def snapshot(extra: Path | None) -> dict[str, Any]:
    import quant_trade

    return {
        "source": str(Path(quant_trade.__file__).resolve().parent),
        "cases": [run_case(case) for case in cases(extra)],
    }


def _walk(left: Any, right: Any, path: str, out: list[str]) -> None:
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            _walk(left.get(key, "<absent>"), right.get(key, "<absent>"), f"{path}.{key}", out)
    elif isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        for index, (a, b) in enumerate(zip(left, right, strict=True)):
            _walk(a, b, f"{path}[{index}]", out)
    elif left != right:
        out.append(f"{path}: {_short(left)} -> {_short(right)}")


def _short(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= 110 else text[:107] + "..."


def _without_date_notes(record: dict[str, Any]) -> dict[str, Any]:
    """The record with the notes that only state the date order taken out."""

    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        if isinstance(value, list):
            return [
                clean(item) for item in value if not (isinstance(item, str) and DATE_NOTE in item)
            ]
        return value

    return {"outcome": record["outcome"], "headline": clean(record["headline"]),
            "result": clean(record["result"])}  # fmt: skip


def differences(base: dict[str, Any], head: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per case: what the base read, what this checkout reads, and
    every field that differs."""
    theirs = {record["name"]: record for record in base["cases"]}
    rows = []
    for record in head["cases"]:
        before = theirs.get(record["name"])
        if before is None:
            rows.append({"name": record["name"], "before": None, "after": record, "paths": ["new"],
                         "only_date_note": False, "short_history": False})  # fmt: skip
            continue
        paths: list[str] = []
        _walk(_without_date_notes(before), _without_date_notes(record), "", paths)
        everything: list[str] = []
        _walk(
            {key: before[key] for key in ("outcome", "headline", "result")},
            {key: record[key] for key in ("outcome", "headline", "result")},
            "",
            everything,
        )
        returns = int(record["headline"].get("observations") or 0) - 1
        short = (
            record["outcome"] == "audited"
            and returns < 3
            and bool(paths)
            and all(path.startswith(SHORT_HISTORY_FIELDS) for path in paths)
        )
        rows.append(
            {
                "name": record["name"],
                "before": before,
                "after": record,
                "paths": paths,
                "only_date_note": bool(everything) and not paths,
                "short_history": short,
            }
        )
    return rows


def intended(row: dict[str, Any]) -> bool:
    """Whether a row that differs is one of the changes the branch makes."""
    return row["name"].startswith(EXPECTED_TO_CHANGE) or bool(row.get("short_history"))


def _cell(record: dict[str, Any] | None) -> str:
    if record is None:
        return "-"
    head = record["headline"]
    if record["outcome"] == "refused":
        return f"refused ({head['code']})"
    perf = head["performance"]

    def short(key: str, percent: bool) -> str:
        text = str(perf.get(key))
        number, _, tag = text.partition(" [")
        try:
            shown = f"{float(number):+.1%}" if percent else f"{float(number):.2f}"
        except ValueError:
            shown = "none"
        return shown if tag.startswith("MEASURED") else f"{shown} {tag.split(']')[0]}"

    return (
        f"{head['class']}, {head['first'][:10]} to {head['last'][:10]}, "
        f"{head['observations']} rows, return {short('total_return', True)}, "
        f"drawdown {short('max_drawdown', True)}, Sharpe {short('sharpe', False)}"
    )


def table(rows: list[dict[str, Any]]) -> str:
    lines = ["| case | base | this checkout | differing fields |", "|---|---|---|---|"]
    for row in rows:
        note = "0"
        if row["paths"]:
            note = str(len(row["paths"]))
            if row.get("short_history"):
                note += " (Sharpe/Sortino of fewer than three returns)"
            elif intended(row):
                note += " (intended)"
            else:
                note += " (NOT INTENDED)"
        elif row["only_date_note"]:
            note = "0 (date-order note added)"
        lines.append(f"| {row['name']} | {_cell(row['before'])} | {_cell(row['after'])} | {note} |")
    return "\n".join(lines)


def _snapshot_in_subprocess(src: Path, extra: Path | None, folder: Path, name: str) -> Any:
    out = folder / f"{name}.json"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(src)
    env["PYTHONHASHSEED"] = "0"
    command = [sys.executable, str(Path(__file__).resolve()), "snapshot", "--out", str(out)]
    if extra is not None:
        command += ["--extra", str(extra)]
    subprocess.run(command, check=True, env=env, cwd=str(folder))
    return json.loads(out.read_text(encoding="utf-8"))


def compare(base_src: Path, extra: Path | None, details: bool) -> int:
    with tempfile.TemporaryDirectory(prefix="rigor-reading-") as folder:
        base = _snapshot_in_subprocess(base_src, extra, Path(folder), "base")
        head = _snapshot_in_subprocess(ROOT / "src", extra, Path(folder), "head")
    print(f"base: {base['source']}")
    print(f"this: {head['source']}")
    rows = differences(base, head)
    print(table(rows))
    unexpected = [row for row in rows if row["paths"] and not intended(row)]
    for row in rows:
        if row["paths"] and (details or row in unexpected):
            print(f"\n{row['name']}:")
            for path in row["paths"][:60]:
                print(f"  {path}")
            if len(row["paths"]) > 60:
                print(f"  ... {len(row['paths']) - 60} more")
    print(f"\n{len(rows)} cases; {len(unexpected)} changed outside the intended ones")
    return 1 if unexpected else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    one = commands.add_parser("snapshot")
    one.add_argument("--out", type=Path, required=True)
    one.add_argument("--extra", type=Path, default=None)
    both = commands.add_parser("compare")
    both.add_argument("--base-src", type=Path, required=True)
    both.add_argument("--extra", type=Path, default=None)
    both.add_argument("--details", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "snapshot":
        args.out.write_text(json.dumps(snapshot(args.extra), ensure_ascii=False), encoding="utf-8")
        return 0
    return compare(args.base_src, args.extra, args.details)


run_audit_case: Callable[[dict[str, Any]], dict[str, Any]] = run_case

if __name__ == "__main__":
    raise SystemExit(main())
