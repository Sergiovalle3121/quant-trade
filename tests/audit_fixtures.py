"""Deterministic synthetic uploads for the backtest-audit tests.

Everything is generated from a seed; nothing here is market data. The
builders return pandas frames, and ``csv_bytes`` turns any of them into the
bytes a client would upload.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

START = "2019-01-02"


def business_days(n: int, start: str = START) -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="B", tz="UTC")


def positive_drift(
    n: int = 1500, *, mean: float = 0.0009, std: float = 0.01, seed: int = 3
) -> pd.DataFrame:
    """A daily equity curve with a real edge: annualised Sharpe around 1.4."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(mean, std, n)
    equity = 10_000.0 * np.cumprod(1.0 + returns)
    return pd.DataFrame({"timestamp": business_days(n), "equity": equity})


def returns_frame(n: int = 600, *, mean: float = 0.0009, std: float = 0.01, seed: int = 5):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"date": business_days(n), "return": rng.normal(mean, std, n)})


def best_of_n_walks(
    trials: int = 100, n: int = 512, *, std: float = 0.01, seed: int = 11
) -> tuple[pd.DataFrame, np.ndarray]:
    """``trials`` unskilled random walks; the winner by Sharpe as an equity
    curve, and the whole matrix as the variants upload."""
    rng = np.random.default_rng(seed)
    matrix = rng.normal(0.0, std, (n, trials))
    sharpes = matrix.mean(axis=0) / matrix.std(axis=0, ddof=1)
    winner = matrix[:, int(np.argmax(sharpes))]
    equity = 10_000.0 * np.cumprod(1.0 + winner)
    return pd.DataFrame({"timestamp": business_days(n), "equity": equity}), matrix


def stale_marks(n: int = 400, *, run: int = 25, seed: int = 2) -> pd.DataFrame:
    """A curve with a long run of identical non-zero daily returns."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0005, 0.01, n)
    returns[100 : 100 + run] = 0.004
    equity = 10_000.0 * np.cumprod(1.0 + returns)
    return pd.DataFrame({"timestamp": business_days(n), "equity": equity})


def spiked(n: int = 400, *, spikes: int = 5, seed: int = 4) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0003, 0.008, n)
    for index in range(spikes):
        returns[50 + 60 * index] = 0.45
    equity = 10_000.0 * np.cumprod(1.0 + returns)
    return pd.DataFrame({"timestamp": business_days(n), "equity": equity})


def trades_frame(
    n: int = 60, *, edge: float = 0.8, seed: int = 9, side: str = "long"
) -> pd.DataFrame:
    """Closed round trips of 10 units at 100 with a mean edge of ``edge``."""
    rng = np.random.default_rng(seed)
    days = business_days(n * 25 + 2)
    move = rng.normal(edge, 1.0, n)
    exit_price = 100.0 + move if side == "long" else 100.0 - move
    return pd.DataFrame(
        {
            "entry_time": days[::25][:n],
            "exit_time": days[1::25][:n],
            "quantity": 10.0,
            "entry_price": 100.0,
            "exit_price": exit_price,
            "side": side,
        }
    )


def benchmark_lower_drift(n: int = 1500, *, seed: int = 21) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0002, 0.012, n)
    return pd.DataFrame(
        {"timestamp": business_days(n), "equity": 100.0 * np.cumprod(1.0 + returns)}
    )


def csv_bytes(frame: pd.DataFrame, *, sep: str = ",") -> bytes:
    return frame.to_csv(index=False, sep=sep).encode("utf-8")


def variants_bytes(matrix: np.ndarray) -> bytes:
    frame = pd.DataFrame(matrix, columns=[f"v{i}" for i in range(matrix.shape[1])])
    return csv_bytes(frame)


def trades_following(equity: pd.DataFrame, *, every: int = 25, quantity: float = 100.0):
    """Closed round trips that realise the curve's own change, one per
    ``every`` rows, so the trades and the equity describe the same account."""
    values = equity["equity"].to_numpy(dtype=float)
    stamps = pd.to_datetime(equity["timestamp"], utc=True)
    rows = []
    for start in range(0, len(values) - every, every):
        end = start + every
        change = values[end] - values[start]
        rows.append(
            {
                "entry_time": stamps.iloc[start],
                "exit_time": stamps.iloc[end],
                "quantity": quantity,
                "entry_price": 100.0,
                "exit_price": 100.0 + change / quantity,
                "side": "long",
            }
        )
    return pd.DataFrame(rows)


def _mt5_money(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ")


def synthetic_mt5_report(
    days: int = 400,
    *,
    edge_pips: float = 1.5,
    seed: int = 17,
    lots: float = 0.5,
    start: str = "2023-01-02",
) -> bytes:
    """An MT5 Strategy Tester HTML report (UTF-16 LE with BOM, like the
    terminal writes it) with one EURUSD round trip per business day."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=days)
    balance = 10_000.0
    price = 1.1
    rows = [
        f"<tr><td>{dates[0]:%Y.%m.%d} 00:00:00</td><td>1</td><td></td><td>balance</td>"
        "<td></td><td></td>"
        "<td></td><td></td><td>0.00</td><td>0.00</td><td>10 000.00</td><td>10 000.00</td>"
        "<td></td></tr>"
    ]
    deal = 2
    for day in dates:
        side = "buy" if rng.random() < 0.5 else "sell"
        sign = 1.0 if side == "buy" else -1.0
        entry = round(price, 5)
        pips = edge_pips + rng.normal(0.0, 25.0)
        exit_price = round(entry + sign * pips * 0.0001, 5)
        price = exit_price
        profit = round(pips * 10.0 * lots, 2)
        stamp = day.strftime("%Y.%m.%d")
        balance -= 3.5
        rows.append(
            f"<tr><td>{stamp} 09:00:00</td><td>{deal}</td><td>EURUSD</td><td>{side}</td>"
            f"<td>in</td><td>{lots}</td><td>{entry:.5f}</td><td>{deal}</td><td>-3.50</td>"
            f"<td>0.00</td><td>0.00</td><td>{_mt5_money(balance)}</td><td></td></tr>"
        )
        balance += profit - 3.5
        close = "sell" if side == "buy" else "buy"
        rows.append(
            f"<tr><td>{stamp} 17:00:00</td><td>{deal + 1}</td><td>EURUSD</td><td>{close}</td>"
            f"<td>out</td><td>{lots}</td><td>{exit_price:.5f}</td><td>{deal + 1}</td>"
            f"<td>-3.50</td><td>0.00</td><td>{profit:.2f}</td><td>{_mt5_money(balance)}</td>"
            "<td></td></tr>"
        )
        deal += 2
    header = (
        "<tr><td><b>Time</b></td><td><b>Deal</b></td><td><b>Symbol</b></td><td><b>Type</b></td>"
        "<td><b>Direction</b></td><td><b>Volume</b></td><td><b>Price</b></td>"
        "<td><b>Order</b></td><td><b>Commission</b></td><td><b>Swap</b></td>"
        "<td><b>Profit</b></td><td><b>Balance</b></td><td><b>Comment</b></td></tr>"
    )
    end = dates[-1].strftime("%Y.%m.%d")
    html_text = (
        "<html><head><title>Strategy Tester Report</title></head><body><table>"
        "<tr><td colspan='13'><b>Strategy Tester Report</b></td></tr>"
        "<tr><td colspan='3'>Expert:</td><td colspan='10'><b>SyntheticEA</b></td></tr>"
        "<tr><td colspan='3'>Symbol:</td><td colspan='10'><b>EURUSD</b></td></tr>"
        f"<tr><td colspan='3'>Period:</td><td colspan='10'><b>H1 (2023.01.02 - {end})</b>"
        "</td></tr>"
        "<tr><td colspan='3'>Currency:</td><td colspan='10'><b>USD</b></td></tr>"
        "<tr><td colspan='3'>Initial Deposit:</td><td colspan='10'><b>10 000.00</b></td></tr>"
        "</table><table>"
        "<tr><th colspan='13'><b>Deals</b></th></tr>"
        + header
        + "".join(rows)
        + "</table></body></html>"
    )
    return b"\xff\xfe" + html_text.encode("utf-16-le")


def synthetic_mt5_optimization(passes: int = 250) -> bytes:
    """An MT5 optimisation export (SpreadsheetML) listing ``passes`` passes."""
    names = ["Pass", "Result", "Profit", "Trades", "FastMA", "SlowMA"]
    head = "".join(f'<Cell><Data ss:Type="String">{name}</Data></Cell>' for name in names)
    rows = []
    for index in range(passes):
        values = [index, 10_000 + index, index, 100, 5 + index % 20, 50 + index // 20]
        rows.append(
            "<Row>"
            + "".join(f'<Cell><Data ss:Type="Number">{value}</Data></Cell>' for value in values)
            + "</Row>"
        )
    return (
        '<?xml version="1.0"?>\n<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
        'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">'
        '<Worksheet ss:Name="Tester Optimizator Results"><Table>'
        f"<Row>{head}</Row>" + "".join(rows) + "</Table></Worksheet></Workbook>"
    ).encode("utf-8")


def signed_in(
    client,
    email: str = "tester@example.com",
    password: str = "long safe phrase",
    *,
    welcome: bool = False,
):
    """Sign ``client`` up (and so in): a preview in paid mode needs an account.

    The account's free full report is spent unless ``welcome`` is true, so
    uploads give the monthly previews. A service whose base URL is https sets
    a ``Secure`` cookie, so the client then talks https too.
    """
    import re

    base_url = getattr(client.app.state, "settings", None)
    if base_url is not None and str(getattr(base_url, "base_url", "")).startswith("https"):
        client.base_url = "https://testserver"
    page = client.get("/registro").text
    match = re.search(r"name='csrf' value='([^']+)'", page)
    assert match, "the sign-up form has no CSRF field"
    client.post(
        "/registro",
        data={"email": email, "password": password, "csrf": match.group(1)},
        follow_redirects=False,
    )
    if client.get("/cuenta", follow_redirects=False).status_code != 200:
        # The account already exists in this database: sign in instead.
        page = client.get("/entrar").text
        match = re.search(r"name='csrf' value='([^']+)'", page)
        assert match, "the sign-in form has no CSRF field"
        client.post(
            "/entrar",
            data={"email": email, "password": password, "csrf": match.group(1)},
            follow_redirects=False,
        )
    assert client.get("/cuenta", follow_redirects=False).status_code == 200, "not signed in"
    if not welcome:
        # Most tests need the monthly previews, not the one free full report.
        from datetime import UTC, datetime

        store = client.app.state.store
        account = store.find_account(email)
        assert account is not None
        store.spend_welcome(account.id, at=datetime.now(UTC))
    return client
