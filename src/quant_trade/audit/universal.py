"""Any trade list: a CSV or XLSX from a platform Rigor has no importer for.

Brokers, exchanges and journals all export a table with one row per closed
trade (entry and exit time, quantity, entry and exit price, profit) or one
row per fill (time, buy or sell, quantity, price). This module recognises
the columns by their names in English, Spanish, Portuguese, French, German
and Italian, or takes the customer's own mapping (``columns``), and turns
the rows into the importers' round trips. Fills are paired first in, first
out per symbol.

Nothing is guessed that the file does not say: a missing required column is
an error that lists the columns found, and every assumption (profit read net
or gross of commission, a side taken from the sign of the quantity) becomes a
warning in the report.
"""

from __future__ import annotations

import re
import statistics
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from quant_trade.audit import importers as imp

UNIVERSAL_TRADES_CSV = "universal_trades_csv"
UNIVERSAL_FILLS_CSV = "universal_fills_csv"

#: Every column a mapping can name, in the order the upload form shows them.
ROLES: tuple[str, ...] = (
    "symbol",
    "side",
    "quantity",
    "entry_time",
    "exit_time",
    "entry_price",
    "exit_price",
    "time",
    "price",
    "profit",
    "commission",
    "swap",
    "multiplier",
    "account",
)

#: One closed trade per row needs these; ``side`` and ``profit`` are optional.
TRADE_ROLES: tuple[str, ...] = ("entry_time", "exit_time", "quantity", "entry_price", "exit_price")
#: One fill per row needs these; the side may come from the quantity's sign.
FILL_ROLES: tuple[str, ...] = ("time", "quantity", "price")


def normalise(name: str) -> str:
    """``Date(UTC)`` -> ``date``, ``Precio de entrada`` -> ``preciodeentrada``.

    Accents, text in brackets, units after a slash and anything that is not a
    letter or a digit are dropped, so one synonym covers every spelling.
    """
    text = unicodedata.normalize("NFKD", name.strip().lstrip("﻿"))
    text = "".join(char for char in text if not unicodedata.combining(char)).lower()
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]", "", text)
    return re.sub(r"[^a-z0-9]", "", text)


def _names(*names: str) -> tuple[str, ...]:
    return tuple(normalise(name) for name in names)


#: Column names per role, most specific first. The first role whose list
#: holds a column's normalised name takes it; a role takes one column.
SYNONYMS: dict[str, tuple[str, ...]] = {
    "entry_time": _names(
        "entry time",
        "entry date",
        "entry datetime",
        "open time",
        "open date",
        "opened",
        "opened at",
        "time open",
        "date open",
        "open datetime",
        "entered at",
        "entry timestamp",
        "start time",
        "entrytime",
        "entry_time",
        "opentime",
        "fecha de entrada",
        "hora de entrada",
        "fecha entrada",
        "fecha apertura",
        "fecha de apertura",
        "hora de apertura",
        "apertura",
        "data de abertura",
        "hora de abertura",
        "abertura",
        "data entrada",
        "heure d'entree",
        "date d'ouverture",
        "heure d'ouverture",
        "ouverture",
        "eroffnung",
        "eroffnungszeit",
        "einstiegszeit",
        "data di apertura",
        "ora di apertura",
        "apertura ora",
    ),
    "exit_time": _names(
        "exit time",
        "exit date",
        "exit datetime",
        "close time",
        "close date",
        "closed",
        "closed at",
        "time close",
        "date close",
        "close datetime",
        "exited at",
        "exit timestamp",
        "end time",
        "exittime",
        "exit_time",
        "closetime",
        "fecha de salida",
        "hora de salida",
        "fecha salida",
        "fecha cierre",
        "fecha de cierre",
        "hora de cierre",
        "cierre",
        "data de fechamento",
        "hora de fechamento",
        "fechamento",
        "data saida",
        "heure de sortie",
        "date de fermeture",
        "heure de fermeture",
        "fermeture",
        "schliessung",
        "schliesszeit",
        "ausstiegszeit",
        "data di chiusura",
        "ora di chiusura",
        "chiusura",
    ),
    "entry_price": _names(
        "entry price",
        "open price",
        "avg entry price",
        "average entry price",
        "avg open price",
        "average open price",
        "price open",
        "entry px",
        "open px",
        "entryprice",
        "entry_price",
        "precio de entrada",
        "precio entrada",
        "precio de apertura",
        "precio apertura",
        "preco de entrada",
        "preco de abertura",
        "prix d'entree",
        "prix d'ouverture",
        "einstiegspreis",
        "eroffnungskurs",
        "eroffnungspreis",
        "prezzo di apertura",
        "prezzo di entrata",
    ),
    "exit_price": _names(
        "exit price",
        "close price",
        "avg exit price",
        "average exit price",
        "avg close price",
        "average close price",
        "price close",
        "exit px",
        "close px",
        "exitprice",
        "exit_price",
        "precio de salida",
        "precio salida",
        "precio de cierre",
        "precio cierre",
        "preco de saida",
        "preco de fechamento",
        "prix de sortie",
        "prix de fermeture",
        "ausstiegspreis",
        "schlusskurs",
        "prezzo di chiusura",
        "prezzo di uscita",
    ),
    "time": _names(
        "time",
        "date",
        "datetime",
        "date time",
        "timestamp",
        "trade time",
        "trade date",
        "execution time",
        "exec time",
        "fill time",
        "filled time",
        "transaction time",
        "created at",
        "created time",
        "update time",
        "date/time",
        "fecha",
        "hora",
        "fecha y hora",
        "fecha hora",
        "data",
        "data e hora",
        "horario",
        "heure",
        "date et heure",
        "datum",
        "zeit",
        "datum/zeit",
        "ora",
        "data e ora",
    ),
    "price": _names(
        "price",
        "fill price",
        "trade price",
        "execution price",
        "exec price",
        "avg price",
        "average price",
        "avg fill price",
        "average filled price",
        "filled price",
        "price at transaction",
        "t. price",
        "precio",
        "precio medio",
        "precio de ejecucion",
        "preco",
        "preco medio",
        "prix",
        "prix moyen",
        "kurs",
        "preis",
        "ausfuhrungskurs",
        "prezzo",
    ),
    "symbol": _names(
        "symbol",
        "instrument",
        "ticker",
        "pair",
        "market",
        "contract",
        "contract name",
        "asset",
        "security",
        "product",
        "underlying",
        "coin",
        "currency pair",
        "simbolo",
        "instrumento",
        "activo",
        "par",
        "mercado",
        "contrato",
        "ativo",
        "ativo/par",
        "symbole",
        "actif",
        "marche",
        "wertpapier",
        "basiswert",
        "strumento",
        "titolo",
    ),
    "side": _names(
        "side",
        "direction",
        "type",
        "action",
        "buy/sell",
        "b/s",
        "long/short",
        "position side",
        "trade type",
        "transaction type",
        "order side",
        "market pos.",
        "lado",
        "direccion",
        "tipo",
        "accion",
        "operacion",
        "compra/venta",
        "sentido",
        "direcao",
        "operacao",
        "sens",
        "achat/vente",
        "richtung",
        "art",
        "kauf/verkauf",
        "direzione",
        "segno",
    ),
    "quantity": _names(
        "quantity",
        "qty",
        "size",
        "volume",
        "lots",
        "lot",
        "units",
        "contracts",
        "shares",
        "executed",
        "filled",
        "filled qty",
        "exec qty",
        "position size",
        "vol",
        "quantity transacted",
        "amount",
        "cantidad",
        "volumen",
        "lotes",
        "unidades",
        "acciones",
        "contratos",
        "tamano",
        "quantidade",
        "qtd",
        "lote",
        "quantite",
        "qte",
        "volume (lots)",
        "menge",
        "anzahl",
        "stuck",
        "quantita",
        "lotti",
    ),
    "profit": _names(
        "profit",
        "pnl",
        "p&l",
        "p/l",
        "pl",
        "profit/loss",
        "profit loss",
        "net profit",
        "net pnl",
        "net p&l",
        "net p/l",
        "realized pnl",
        "realised pnl",
        "realized p&l",
        "realized p/l",
        "realized profit",
        "closed pnl",
        "closed p&l",
        "gross pnl",
        "gross p&l",
        "gross profit",
        "fifo pnl realized",
        "result",
        "gain",
        "beneficio",
        "ganancia",
        "resultado",
        "ganancia/perdida",
        "g/p",
        "pyg",
        "lucro",
        "lucro/prejuizo",
        "resultado liquido",
        "benefice",
        "gain/perte",
        "resultat",
        "gewinn",
        "gewinn/verlust",
        "ergebnis",
        "profitto",
        "utile",
        "risultato",
    ),
    "commission": _names(
        "commission",
        "commissions",
        "comm",
        "fee",
        "fees",
        "trading fee",
        "trading fees",
        "ib commission",
        "fees and/or spread",
        "exchange fee",
        "clearing fee",
        "nfa fee",
        "brokerage",
        "comision",
        "comisiones",
        "costes",
        "tarifa",
        "comissao",
        "taxa",
        "taxas",
        "corretagem",
        "frais",
        "gebuhr",
        "gebuhren",
        "provision",
        "commissione",
        "commissioni",
    ),
    "swap": _names(
        "swap",
        "swaps",
        "rollover",
        "financing",
        "funding",
        "funding fee",
        "overnight fee",
        "intereses",
        "financiacion",
        "financiamento",
        "financement",
        "finanzierung",
    ),
    "multiplier": _names(
        "multiplier",
        "contract multiplier",
        "point value",
        "contract size",
        "mult",
        "multiplicador",
        "valor por punto",
        "tamano del contrato",
        "multiplicateur",
        "multiplikator",
        "moltiplicatore",
    ),
    "account": _names(
        "account", "account name", "account id", "cuenta", "conta", "compte", "konto", "conto"
    ),  # fmt: skip
}

LONG_WORDS = frozenset(
    {"long", "buy", "b", "l", "bought", "bot", "compra", "largo", "comprar", "achat",
     "acheter", "kauf", "kaufen", "acquisto", "buytoopen", "buytoclose", "bto", "btc"}
)  # fmt: skip
SHORT_WORDS = frozenset(
    {"short", "sell", "s", "sold", "sld", "venta", "corto", "vender", "vente", "vendre",
     "verkauf", "verkaufen", "vendita", "venda", "selltoopen", "selltoclose", "sto", "stc"}
)  # fmt: skip


@dataclass(frozen=True)
class ColumnMap:
    """Which column plays each role, and whether rows are trades or fills."""

    shape: str
    columns: dict[str, int]
    names: dict[str, str] = field(default_factory=dict)
    #: Every cost column added up into the commission (``commission`` first).
    fees: tuple[int, ...] = ()


def _role_of(name: str) -> tuple[str, int] | None:
    """The role a column name plays and its rank in that role's list."""
    key = normalise(name)
    if not key:
        return None
    for role, names in SYNONYMS.items():
        if key in names:
            return role, names.index(key)
    return None


def _ranked(header: Sequence[str]) -> dict[str, list[tuple[int, int]]]:
    found: dict[str, list[tuple[int, int]]] = {}
    for position, name in enumerate(header):
        match = _role_of(str(name))
        if match is not None:
            found.setdefault(match[0], []).append((match[1], position))
    return {role: sorted(options) for role, options in found.items()}


def guess_columns(header: Sequence[str]) -> dict[str, int]:
    """Each role's column by name: the most specific name wins (``Side``
    before ``Type``, ``Executed`` before ``Amount``), then the first column.

    A table that repeats a time column (``Time ... Time``, as MQL5 signal
    histories do) holds entry and exit on one row, so its first and second
    time are the entry and exit, and a repeated price likewise; it is never
    read as a list of fills.
    """
    ranked = _ranked(header)
    columns = {role: options[0][1] for role, options in ranked.items()}
    times = sorted(position for _, position in ranked.get("time", []))
    if len(times) >= 2:
        del columns["time"]
        columns.setdefault("entry_time", times[0])
        columns.setdefault("exit_time", times[1])
        prices = sorted(position for _, position in ranked.get("price", []))
        columns.pop("price", None)
        if len(prices) >= 2:
            columns.setdefault("entry_price", prices[0])
            columns.setdefault("exit_price", prices[1])
    return columns


def _shape(columns: Mapping[str, int]) -> str | None:
    if all(role in columns for role in TRADE_ROLES):
        return UNIVERSAL_TRADES_CSV
    if all(role in columns for role in FILL_ROLES):
        return UNIVERSAL_FILLS_CSV
    return None


def looks_like_trades(header: Sequence[str]) -> bool:
    """True when the header names a closed-trade or a fill table."""
    return _shape(guess_columns(header)) is not None


def resolve(header: Sequence[str], chosen: Mapping[str, str] | None = None) -> ColumnMap:
    """The mapping for ``header``: the customer's ``chosen`` role -> column
    name first, each role not chosen guessed from the names.

    Raises ``ReportFormatError`` naming the columns found and the ones
    missing when neither a trade nor a fill table can be read.
    """
    positions: dict[str, int] = {}
    for index, name in enumerate(header):
        positions.setdefault(str(name).strip(), index)
    columns = guess_columns(header)
    fees = [position for _, position in _ranked(header).get("commission", [])]
    taken: dict[str, int] = {}
    for role, name in (chosen or {}).items():
        if role not in ROLES or not name:
            continue
        found_at = positions.get(str(name).strip())
        if found_at is None:
            raise imp.ReportFormatError(
                "universal_unknown_column",
                f"the column '{imp._clip(str(name), 60)}' is not in the file",
                f"la columna «{imp._clip(str(name), 60)}» no está en el archivo",
            )
        taken[role] = found_at
    if taken:
        # A column the customer assigned is no longer free for a guessed role.
        columns = {role: index for role, index in columns.items() if index not in taken.values()}
        columns.update(taken)
        fees = (
            [taken["commission"]]
            if "commission" in taken
            else [index for index in fees if index not in taken.values()]
        )
    shape = _shape(columns)
    if shape is None:
        raise missing_columns(header, columns)
    dropped = (
        {"time", "price"}
        if shape == UNIVERSAL_TRADES_CSV
        else {"entry_time", "exit_time", "entry_price", "exit_price"}
    )
    columns = {role: index for role, index in columns.items() if role not in dropped}
    names = {role: str(header[index]).strip() for role, index in columns.items()}
    return ColumnMap(shape, columns, names, tuple(fees))


_ROLE_TEXT = {
    "en": {
        "entry_time": "entry time", "exit_time": "exit time", "quantity": "quantity",
        "entry_price": "entry price", "exit_price": "exit price", "time": "time",
        "price": "price",
    },
    "es": {
        "entry_time": "hora de entrada", "exit_time": "hora de salida", "quantity": "cantidad",
        "entry_price": "precio de entrada", "exit_price": "precio de salida", "time": "hora",
        "price": "precio",
    },
}  # fmt: skip


def missing_columns(header: Sequence[str], columns: Mapping[str, int]) -> imp.ReportFormatError:
    """The error for a table that is neither a trade list nor a fill list."""
    trade_gap = [role for role in TRADE_ROLES if role not in columns]
    fill_gap = [role for role in FILL_ROLES if role not in columns]
    gap = trade_gap if len(trade_gap) <= len(fill_gap) else fill_gap
    listed = ", ".join(imp._clip(str(name), 40) for name in header[:20] if str(name).strip())
    en = ", ".join(_ROLE_TEXT["en"][role] for role in gap)
    es = ", ".join(_ROLE_TEXT["es"][role] for role in gap)
    return imp.ReportFormatError(
        "universal_columns_missing",
        f"the file has no column we recognise as {en}. Columns found: {listed}. Rename "
        "those columns in the file (for example Entry time, Exit time, Quantity, Entry price, "
        "Exit price, Profit) and upload it again",
        f"el archivo no tiene una columna que reconozcamos como {es}. Columnas encontradas: "
        f"{listed}. Cambia el nombre de esas columnas en el archivo (por ejemplo Fecha de "
        "entrada, Fecha de salida, Cantidad, Precio de entrada, Precio de salida, Resultado) "
        "y vuelve a subirlo",
    )


def _amount(value: str, decimal: str) -> float | None:
    """A number, also when a unit follows it (``0.0015 BTC``, ``12.5USDT``)."""
    number = imp._num(value, decimal=decimal)
    if number is not None:
        return number
    match = re.fullmatch(r"\s*([-+(]?[\d.,\s]+\)?)\s*[A-Za-z]{2,10}\s*", value or "")
    return imp._num(match.group(1), decimal=decimal) if match else None


def _times(values: list[str], serial: bool) -> imp._TimeColumn:
    """A time column; whole-number Unix times (seconds or milliseconds) too."""
    filled = [value for value in values if value]
    if filled and all(re.fullmatch(r"\d{10}(\d{3})?", value) for value in filled):
        parsed: list[datetime | None] = [
            datetime.fromtimestamp(int(value) / (1000 if len(value) == 13 else 1), tz=UTC)
            if value
            else None
            for value in values
        ]
        return imp._TimeColumn(parsed, False)
    return imp._parse_times(values, serial_numbers=serial)


def _side(text: str) -> str | None:
    raw = text.strip()
    if raw in {"1", "+1"}:
        return "long"
    if raw == "-1":
        return "short"
    word = normalise(raw)
    if word in LONG_WORDS:
        return "long"
    if word in SHORT_WORDS:
        return "short"
    if word.startswith("buy") or word.startswith("compra"):
        return "long"
    if word.startswith("sell") or word.startswith("vend"):
        return "short"
    return None


_UNIT = re.compile(r"[\d.,)\s]([A-Za-z]{2,10})\s*$")


def _paid(row: Sequence[str], fees: Sequence[int], decimal: str, symbol: str) -> tuple[float, int]:
    """Costs of one row: every fee column, whatever its sign, as a positive
    sum, and how many fee cells were left out because they are charged in
    another coin than the price (``0.001 BNB`` on ``BTCUSDT``)."""
    paid = 0.0
    other = 0
    plain = re.sub(r"[^A-Z0-9]", "", symbol.upper())
    for index in fees:
        if index >= len(row) or not row[index].strip():
            continue
        unit = _UNIT.search(row[index])
        amount = abs(_amount(row[index], decimal) or 0.0)
        if unit and amount and not (plain and plain.endswith(unit.group(1).upper())):
            other += 1
            continue
        paid += amount
    return paid, other


def _cell(row: Sequence[str], columns: Mapping[str, int], role: str) -> str:
    index = columns.get(role)
    return row[index] if index is not None and index < len(row) else ""


NET_PROFIT_WARNING = (
    "the profit column already subtracts commission (it matches the price move after "
    "costs), so it was read as net"
)
NO_PROFIT_WARNING = (
    "the file has no profit column: each trade's result is the price move times the "
    "quantity, with no contract multiplier"
)
SIGNED_SIDE_WARNING = "no side column; the side was taken from the sign of the quantity"
PROFIT_SIDE_WARNING = "no side column; the side was taken from the sign of the profit"
OTHER_COIN_WARNING = (
    "{n} fee(s) charged in another coin than the price were left out of the costs, so "
    "costs are understated"
)


def parse(
    header: list[str],
    rows: list[list[str]],
    delimiter: str,
    chosen: Mapping[str, str] | None = None,
    *,
    serial_dates: bool = False,
) -> imp._Draft:
    """Read a trade or fill table into a draft for ``importers._assemble``."""
    mapping = resolve(header, chosen)
    decimal = "," if delimiter == ";" else "."
    draft = imp._Draft(mapping.shape, [])
    for role in ROLES:
        if role == "commission" and mapping.fees:
            listed = ", ".join(str(header[index]).strip() for index in mapping.fees)
            draft.metadata["column_commission"] = imp._clip(listed, 120)
        elif role in mapping.names:
            draft.metadata[f"column_{role}"] = imp._clip(mapping.names[role], 60)
    accounts = [_cell(row, mapping.columns, "account").strip() for row in rows]
    if len(set(accounts)) > 1 and mapping.shape == UNIVERSAL_TRADES_CSV:
        closed: dict[str, int] = {}
        for account in accounts:
            closed[account] = closed.get(account, 0) + 1
        rows = imp._busiest_account(rows, accounts, closed, draft.warnings)
    if mapping.shape == UNIVERSAL_TRADES_CSV:
        _trades(draft, mapping, rows, decimal, serial_dates)
    else:
        _fills(draft, mapping, rows, decimal, serial_dates)
    if "commission" in mapping.columns or "swap" in mapping.columns:
        draft.itemised = {name for name in ("commission", "swap") if name in mapping.columns}
    if (
        draft.trips
        and draft.itemised
        and all(trip.commission == 0 and trip.swap == 0 for trip in draft.trips)
    ):
        draft.warnings.append("every trade has zero commission and fees")
    return draft


@dataclass
class _Row:
    side: str | None
    volume: float
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    profit: float | None
    paid: float
    swap: float
    symbol: str


def _trades(
    draft: imp._Draft, mapping: ColumnMap, rows: list[list[str]], decimal: str, serial: bool
) -> None:
    columns = mapping.columns
    entry_times = _times([_cell(row, columns, "entry_time") for row in rows], serial)
    exit_times = _times([_cell(row, columns, "exit_time") for row in rows], serial)
    draft.naive_times = entry_times.naive or exit_times.naive
    parsed: list[_Row] = []
    signed = False
    other_coin = 0
    for position, row in enumerate(rows):
        volume = _amount(_cell(row, columns, "quantity"), decimal)
        entry_price = _amount(_cell(row, columns, "entry_price"), decimal)
        exit_price = _amount(_cell(row, columns, "exit_price"), decimal)
        profit = _amount(_cell(row, columns, "profit"), decimal) if "profit" in columns else None
        entry_time = entry_times.values[position]
        exit_time = exit_times.values[position]
        side = _side(_cell(row, columns, "side")) if "side" in columns else None
        symbol = " ".join(_cell(row, columns, "symbol").split()).upper()
        paid, other = _paid(row, mapping.fees, decimal, symbol)
        other_coin += other
        if (
            volume is None
            or volume == 0
            or entry_price is None
            or exit_price is None
            or entry_time is None
            or exit_time is None
            or ("side" in columns and side is None)
            or ("profit" in columns and profit is None)
        ):
            draft.invalid_rows += 1
            continue
        if side is None and volume < 0:
            signed = True
        parsed.append(
            _Row(
                side=side,
                volume=volume,
                entry_time=entry_time,
                exit_time=exit_time,
                entry_price=entry_price,
                exit_price=exit_price,
                profit=profit,
                paid=paid,
                swap=_amount(_cell(row, columns, "swap"), decimal) or 0.0,
                symbol=symbol,
            )
        )
    if other_coin:
        draft.warnings.append(OTHER_COIN_WARNING.format(n=other_coin))
    if "side" not in columns:
        if signed:
            draft.warnings.append(SIGNED_SIDE_WARNING)
            for item in parsed:
                item.side = "long" if item.volume > 0 else "short"
        elif "profit" in columns:
            draft.warnings.append(PROFIT_SIDE_WARNING)
            for item in parsed:
                move = item.exit_price - item.entry_price
                item.side = "short" if move * (item.profit or 0.0) < 0 else "long"
        else:
            draft.warnings.append("no side column; every trade treated as long")
            for item in parsed:
                item.side = "long"
    net = _profit_is_net(
        [
            (
                item.symbol,
                (1.0 if item.side == "long" else -1.0)
                * (item.exit_price - item.entry_price)
                * abs(item.volume),
                item.profit,
                item.paid,
            )
            for item in parsed
        ],
        mapping.names.get("profit", ""),
    )
    if net:
        draft.warnings.append(NET_PROFIT_WARNING)
    if "profit" not in columns:
        draft.warnings.append(NO_PROFIT_WARNING)
    for item in parsed:
        direction = 1.0 if item.side == "long" else -1.0
        gross = (
            item.profit + (item.paid if net else 0.0)
            if item.profit is not None
            else direction * (item.exit_price - item.entry_price) * abs(item.volume)
        )
        draft.trips.append(
            imp._Trip(
                symbol=item.symbol,
                side=item.side or "long",
                volume=abs(item.volume),
                entry_time=item.entry_time,
                exit_time=item.exit_time,
                entry_price=item.entry_price,
                exit_price=item.exit_price,
                gross=gross,
                commission=-item.paid,
                swap=item.swap,
            )
        )


def _profit_is_net(items: list[tuple[str, float, float | None, float]], column_name: str) -> bool:
    """Whether a profit column already subtracts commission.

    ``items`` are (symbol, price move x quantity, profit, commission paid).
    Each hypothesis fits one money-per-point size per symbol; the one whose
    profits the price moves explain more closely wins. With no commission
    to tell them apart, a column named "net" is net and any other is gross.
    """
    usable = [item for item in items if item[2] is not None and item[1] != 0]
    named_net = "net" in normalise(column_name) or "neto" in normalise(column_name)
    if not usable or all(item[3] == 0 for item in usable):
        return named_net

    def miss(add_back: bool) -> float:
        total = 0.0
        by_symbol: dict[str, list[tuple[float, float]]] = {}
        for symbol, raw, profit, paid in usable:
            gross = (profit or 0.0) + (paid if add_back else 0.0)
            by_symbol.setdefault(symbol, []).append((raw, gross))
        for pairs in by_symbol.values():
            size = statistics.median(gross / raw for raw, gross in pairs)
            total += sum(abs(gross - size * raw) for raw, gross in pairs)
        return total

    as_gross, as_net = miss(False), miss(True)
    if abs(as_gross - as_net) <= 1e-9 * max(1.0, as_gross):
        return named_net
    return as_net < as_gross


def _fills(
    draft: imp._Draft, mapping: ColumnMap, rows: list[list[str]], decimal: str, serial: bool
) -> None:
    """Pair fills first in, first out per account and symbol into round trips.

    A closing fill's own realised profit, when the file has one, is shared
    among the trips it closes by quantity; otherwise the trip's result is the
    price move times quantity times the multiplier column (1 without one).
    """
    columns = mapping.columns
    times = _times([_cell(row, columns, "time") for row in rows], serial)
    draft.naive_times = times.naive
    fills: list[tuple[datetime, int, str, str, float, float, float, float | None, float]] = []
    signed = False
    other_coin = 0
    for position, row in enumerate(rows):
        quantity = _amount(_cell(row, columns, "quantity"), decimal)
        price = _amount(_cell(row, columns, "price"), decimal)
        moment = times.values[position]
        side = _side(_cell(row, columns, "side")) if "side" in columns else None
        if quantity is None or quantity == 0 or price is None or price <= 0 or moment is None:
            draft.invalid_rows += 1
            continue
        if side is None:
            if "side" in columns:
                draft.invalid_rows += 1
                continue
            signed = True
            sign = 1.0 if quantity > 0 else -1.0
        else:
            sign = 1.0 if side == "long" else -1.0
        multiplier = (
            _amount(_cell(row, columns, "multiplier"), decimal) if "multiplier" in columns else None
        )
        profit = _amount(_cell(row, columns, "profit"), decimal) if "profit" in columns else None
        symbol = " ".join(_cell(row, columns, "symbol").split()).upper()
        paid, other = _paid(row, mapping.fees, decimal, symbol)
        other_coin += other
        fills.append(
            (
                moment,
                position,
                _cell(row, columns, "account").strip(),
                symbol,
                sign * abs(quantity),
                price,
                paid,
                profit,
                multiplier if multiplier and multiplier > 0 else 1.0,
            )
        )
    if signed:
        draft.warnings.append(SIGNED_SIDE_WARNING)
    if other_coin:
        draft.warnings.append(OTHER_COIN_WARNING.format(n=other_coin))
    open_lots: dict[tuple[str, str], list[list[Any]]] = {}
    trips: dict[str, list[tuple[imp._Trip, float | None]]] = {}
    for moment, _, account, symbol, signed_qty, price, fee, profit, multiplier in sorted(fills):
        lots = open_lots.setdefault((account, symbol), [])
        left = abs(signed_qty)
        fee_per_unit = fee / left
        closing = min(left, sum(abs(lot[0]) for lot in lots if (lot[0] > 0) != (signed_qty > 0)))
        while left > 0 and lots and (lots[0][0] > 0) != (signed_qty > 0):
            lot = lots[0]
            closed = min(left, abs(lot[0]))
            side = "long" if lot[0] > 0 else "short"
            move = (price - lot[1]) if side == "long" else (lot[1] - price)
            share = None if profit is None else profit * closed / closing
            trip = imp._Trip(
                symbol=symbol,
                side=side,
                volume=closed,
                entry_time=lot[2],
                exit_time=moment,
                entry_price=lot[1],
                exit_price=price,
                gross=move * closed * multiplier,
                commission=-(lot[3] + fee_per_unit) * closed,
            )
            trips.setdefault(account, []).append((trip, share))
            lot[0] -= closed if lot[0] > 0 else -closed
            left -= closed
            if lot[0] == 0:
                lots.pop(0)
        if left > 0:
            lots.append([left if signed_qty > 0 else -left, price, moment, fee_per_unit])
    closed_by_account = {account: len(listed) for account, listed in trips.items()}
    chosen = imp._busiest_account(
        [[account] for account in trips], list(trips), closed_by_account, draft.warnings
    )
    kept = {row[0] for row in chosen}
    pairs = [pair for account in kept for pair in trips[account]]
    still_open = sum(1 for (account, _), lots in open_lots.items() if account in kept and lots)
    if still_open:
        draft.warnings.append(
            f"{still_open} position(s) still open at the end of the report; excluded "
            "from the closed trades"
        )
    reported = [pair for pair in pairs if pair[1] is not None and pair[1] != 0]
    if "profit" in columns and any(pair[1] is not None for pair in pairs):
        net = _profit_is_net(
            [(trip.symbol, trip.gross, share, -trip.commission) for trip, share in reported],
            mapping.names.get("profit", ""),
        )
        if net:
            draft.warnings.append(NET_PROFIT_WARNING)
        for trip, share in pairs:
            if share is not None:
                trip.gross = share - (trip.commission if net else 0.0)
    elif "multiplier" not in columns:
        draft.warnings.append(NO_PROFIT_WARNING)
    else:
        draft.sized = True
    draft.trips = sorted((pair[0] for pair in pairs), key=lambda t: (t.exit_time, t.entry_time))


__all__ = [
    "FILL_ROLES",
    "ROLES",
    "SYNONYMS",
    "TRADE_ROLES",
    "UNIVERSAL_FILLS_CSV",
    "UNIVERSAL_TRADES_CSV",
    "guess_columns",
    "looks_like_trades",
    "missing_columns",
    "normalise",
    "parse",
    "resolve",
]
