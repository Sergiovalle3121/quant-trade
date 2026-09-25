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
from datetime import UTC, datetime, timedelta
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
    # casefold, not lower: German ``ß`` becomes ``ss`` (``Schließzeit``).
    text = "".join(char for char in text if not unicodedata.combining(char)).casefold()
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]", "", text)
    return re.sub(r"[^a-z0-9]", "", text)


def _names(*names: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(normalise(name) for name in names))


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
        "opened date",
        "open date/time",
        "opening time",
        "open datetime utc",
        "entry date/time",
        "bought timestamp",
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
        "date de cloture",
        "heure de cloture",
        "cloture",
        "fermeture",
        "schliessung",
        "schliesszeit",
        "ausstiegszeit",
        "data di chiusura",
        "ora di chiusura",
        "chiusura",
        "closed date",
        "close date/time",
        "closing time",
        "exit date/time",
        "sold timestamp",
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
        "cost per share",
        "open rate",
        "opening price",
        "buy price",
        "avg. buy",
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
        "prix de cloture",
        "ausstiegspreis",
        "schlusskurs",
        "prezzo di chiusura",
        "prezzo di uscita",
        "proceeds per share",
        "close rate",
        "closing price",
        "sell price",
        "avg. sell",
    ),
    "time": _names(
        "fill time",
        "filled time",
        "exec time",
        "execution time",
        "trade time",
        "transaction date",
        "transactiondate",
        "activity/trade date",
        "run date",
        "date/time",
        "datetime",
        "trade time utc",
        "tradecreatedat",
        "created at",
        "timestamp",
        "time",
        "date",
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
        "t/d",
    ),
    "price": _names(
        "fill price",
        "avg fill price",
        "filled avg price",
        "average fill price",
        "avg. fill price",
        "filled average price",
        "average filled price",
        "avg price",
        "average price",
        "execution price",
        "exec price",
        "trade price",
        "t. price",
        "tradeprice",
        "price at transaction",
        "filled price",
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
        "opening direction",
        "side",
        "buy/sell",
        "b/s",
        "buy sell",
        "action",
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
        "filled quantity",
        "fill qty",
        "filled qty",
        "paired qty",
        "closing quantity",
        "quantity #",
        "no. of shares",
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
        "gain/loss",
        "realized profit",
        "realized p/l",
        "net usd",
        "net profit usd",
        "closed p&l",
        "gain/loss ($)",
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
        "kommission",
        "gebuhren",
        "provision",
        "commissione",
        "commissioni",
        "fees & comm",
        "commissions & fees",
        "commission amount",
        "comm/fee",
        "comm/fee/tax",
        "ib commission",
        "commission ($)",
        "fees ($)",
        "opening fee",
        "closing fee",
        "platform fee",
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
    "fee_currency": _names(
        "fee coin",
        "fee currency",
        "fee asset",
        "commission asset",
        "commission currency",
        "ib commission currency",
        "moneda de la comision",
    ),
    "account": _names(
        "account", "account name", "account id", "cuenta", "conta", "compte", "konto", "conto"
    ),  # fmt: skip
}

LONG_WORDS = frozenset(
    {"long", "buy", "b", "l", "bought", "bot", "compra", "largo", "comprar", "achat",
     "acheter", "kauf", "kaufen", "acquisto", "buytoopen", "buytoclose", "bto", "btc", "bc"}
)  # fmt: skip
SHORT_WORDS = frozenset(
    {"short", "sell", "s", "sold", "sld", "venta", "corto", "vender", "vente", "vendre",
     "verkauf", "verkaufen", "vendita", "venda", "selltoopen", "selltoclose", "sto", "stc", "ss",
     "sshrt"}
)  # fmt: skip


@dataclass(frozen=True)
class ColumnMap:
    """Which column plays each role, and whether rows are trades or fills."""

    shape: str
    columns: dict[str, int]
    names: dict[str, str] = field(default_factory=dict)
    #: Every cost column added up into the commission (``commission`` first).
    fees: tuple[int, ...] = ()
    #: Another date column, for a fill time that holds only the clock.
    date_column: int | None = None


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
    repeated: dict[str, list[int]] = {}
    for _, position in ranked.get("time", []):
        repeated.setdefault(normalise(str(header[position])), []).append(position)
    times: list[int] = []
    for positions in repeated.values():
        if len(positions) > len(times):
            times = sorted(positions)
    if len(times) >= 2:
        del columns["time"]
        columns.setdefault("entry_time", times[0])
        columns.setdefault("exit_time", times[1])
        prices = sorted(
            position
            for _, position in ranked.get("price", [])
            if normalise(str(header[position])) == normalise(str(header[ranked["price"][0][1]]))
        )
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


def _refuse_shared_columns(header: Sequence[str], taken: Mapping[str, int]) -> None:
    """One column chosen for two fields (entry and exit time, say) would make
    every trade last zero seconds or move zero points: refused, naming both."""
    seen: dict[int, str] = {}
    for role, index in taken.items():
        if index in seen:
            first, second = seen[index], role
            name = imp._clip(str(header[index]), 60)
            raise imp.ReportFormatError(
                "universal_column_twice",
                f"the column '{name}' was chosen for two fields ({_ROLE_TEXT['en'][first]} "
                f"and {_ROLE_TEXT['en'][second]}); choose a different column for each",
                f"la columna «{name}» se eligió para dos campos ({_ROLE_TEXT['es'][first]} "
                f"y {_ROLE_TEXT['es'][second]}); elige una columna distinta para cada uno",
            )
        seen[index] = role


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
    _refuse_shared_columns(header, taken)
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
    if "swap" in columns and "swap" not in taken:
        # A second financing column (XTB lists Swap and Rollover) is a cost too.
        fees += [
            position
            for _, position in _ranked(header).get("swap", [])
            if position != columns["swap"] and position not in taken.values()
        ]
    names = {role: str(header[index]).strip() for role, index in columns.items()}
    others = [
        position
        for _, position in _ranked(header).get("time", [])
        if position != columns.get("time")
    ]
    return ColumnMap(shape, columns, names, tuple(fees), others[0] if others else None)


_ROLE_TEXT = {
    "en": {
        "entry_time": "entry time", "exit_time": "exit time", "quantity": "quantity",
        "entry_price": "entry price", "exit_price": "exit price", "time": "time",
        "price": "price", "symbol": "symbol", "side": "side", "profit": "profit",
        "commission": "commission", "swap": "swap", "multiplier": "multiplier",
        "account": "account",
    },
    "es": {
        "entry_time": "hora de entrada", "exit_time": "hora de salida", "quantity": "cantidad",
        "entry_price": "precio de entrada", "exit_price": "precio de salida", "time": "hora",
        "price": "precio", "symbol": "símbolo", "side": "lado", "profit": "resultado",
        "commission": "comisión", "swap": "swap", "multiplier": "multiplicador",
        "account": "cuenta",
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
        f"the file has no column we recognise as {en}. Columns found: {listed}. Name "
        "them under 'Platform not listed, or its file fails? Name its columns' on the form, "
        "or rename those columns in the file (for example Entry time, Exit time, Quantity, "
        "Entry price, Exit price) and upload it again",
        f"el archivo no tiene una columna que reconozcamos como {es}. Columnas encontradas: "
        f"{listed}. Indícalas en «¿Tu plataforma no aparece o su archivo da error? Indica "
        "sus columnas» del formulario, o cambia el nombre de esas columnas en el archivo (por "
        "ejemplo Fecha de entrada, Fecha de salida, Cantidad, Precio de entrada, Precio de "
        "salida) y vuelve a subirlo",
    )


def statement_section(table: list[list[str]]) -> tuple[list[str], list[list[str]]] | None:
    """The trades section of a multi-section statement, as one table.

    Interactive Brokers' Activity Statement prefixes every line with its
    section (``Trades,Header,...`` then ``Trades,Data,Order,...``; one header
    per asset class, merged here by column name, subtotal lines dropped).
    thinkorswim's Account Statement puts a title line (``Account Trade
    History``) above the section's header. ``None`` when neither is there.
    """
    headers = [row for row in table if len(row) > 2 and row[0] == "Trades" and row[1] == "Header"]
    if headers:
        names: list[str] = []
        for header in headers:
            names += [name for name in header[2:] if name not in names]
        merged: list[list[str]] = []
        current: list[str] = []
        for row in table:
            if len(row) < 3 or row[0] != "Trades":
                continue
            if row[1] == "Header":
                current = row[2:]
                continue
            if row[1] != "Data" or (
                current
                and current[0] == "DataDiscriminator"
                and row[2] not in {"Order", "Trade", "Execution"}
            ):
                continue  # fmt: skip
            cells = dict(zip(current, row[2:], strict=False))
            merged.append([cells.get(name, "") for name in names])
        return names, merged
    for index, row in enumerate(table[:-1]):
        title = [cell for cell in row if cell.strip()]
        if len(title) == 1 and normalise(title[0]) == "accounttradehistory":
            body: list[list[str]] = []
            for line in table[index + 2 :]:
                if sum(1 for cell in line if cell.strip()) <= 1:
                    break
                body.append(line)
            return table[index + 1], body
    return None


#: A summary row's first filled cell (XTB ends its closed positions with "Total").
TOTAL_WORDS = frozenset({"total", "totals", "totales", "totaal", "gesamt", "suma", "razem"})


def without_totals(rows: list[list[str]]) -> list[list[str]]:
    """The rows minus a summary row, which is neither a trade nor damage."""

    def first(row: list[str]) -> str:
        return next((cell for cell in row if cell.strip()), "")

    return [row for row in rows if normalise(first(row)) not in TOTAL_WORDS]


def only_fills(header: Sequence[str], rows: list[list[str]]) -> list[list[str]]:
    """Sierra Chart's Trade Activity Log mixes order events with fills; keep
    the fills when an activity column says which is which."""
    kinds = [i for i, name in enumerate(header) if normalise(str(name)) == "activitytype"]
    if not kinds:
        return rows
    return [row for row in rows if "fill" in (row[kinds[0]] if kinds[0] < len(row) else "").lower()]


def _amount(value: str, decimal: str) -> float | None:
    """A number, also when a unit follows it (``0.0015 BTC``, ``12.5USDT``)."""
    value = re.sub(r"^([-+]?)\s*[$€£¥]\s*", r"\1", (value or "").strip())
    number = imp._num(value, decimal=decimal)
    if number is not None:
        return number
    match = re.fullmatch(r"\s*([-+(]?[\d.,\s]+\)?)\s*[A-Za-z]{2,10}\s*", value or "")
    return imp._num(match.group(1), decimal=decimal) if match else None


#: Zone abbreviations platforms print after a time, in hours from UTC.
_ZONES = {
    "UTC": 0, "GMT": 0, "Z": 0, "ET": -5, "EST": -5, "EDT": -4, "CT": -6, "CST": -6,
    "CDT": -5, "MT": -7, "MST": -7, "MDT": -6, "PT": -8, "PST": -8, "PDT": -7,
    "CET": 1, "CEST": 2, "BST": 1, "EET": 2, "EEST": 3, "JST": 9, "HKT": 8, "SGT": 8,
    "AEST": 10, "AEDT": 11,
}  # fmt: skip
_COMPACT = re.compile(r"^(\d{4})(\d{2})(\d{2})(?:[;,T ]+(\d{2}):?(\d{2}):?(\d{2})?)?$")
_SHORT_YEAR = re.compile(r"^(\d{1,2})([/.\-])(\d{1,2})\2(\d{2})(?=\s|$)")
_TAIL_OFFSET = re.compile(r"\s*(?:(?:UTC|GMT)?([+-])(\d{1,2}):?(\d{2})?)$")
_CLOCK = re.compile(r"^\d{1,2}:\d{2}(:\d{2}(\.\d+)?)?(\s*[AaPp][Mm])?$")
_ISO_DAY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_DAY_MONTH = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})")


def _clean_time(text: str) -> tuple[str, int | None]:
    """A platform time rewritten for ``importers._parse_times``, and the
    offset from UTC in minutes it carried (``None`` when it carried none).

    Handles ``20260115;093000`` (Interactive Brokers), ``2026-01-15, 09:30:00``,
    ``1/15/26 09:30`` (two-digit years), ``01/15/2026 09:30:00 EST`` and
    ``10/01/2025 21:13:23 +02:00`` (a zone after a day-first date).
    """
    value = text.strip()
    if not value:
        return value, None
    compact = _COMPACT.match(value)
    if compact:
        year, month, day, hour, minute, second = compact.groups()
        clock = f" {hour}:{minute}:{second or '00'}" if hour else ""
        return f"{year}-{month}-{day}{clock}", None
    value = re.sub(r"^(\S+?)[,;]\s*(?=\d)", r"\1 ", value)
    offset: int | None = None
    words = value.rsplit(" ", 1)
    if len(words) == 2 and words[1].upper() in _ZONES:
        offset = _ZONES[words[1].upper()] * 60
        value = words[0]
    elif not _ISO_DAY.match(value) and " " in value:
        tail = _TAIL_OFFSET.search(value)
        if tail:
            sign = 1 if tail.group(1) == "+" else -1
            offset = sign * (int(tail.group(2)) * 60 + int(tail.group(3) or 0))
            value = value[: tail.start()]
    short = _SHORT_YEAR.match(value)
    if short:
        value = f"{short.group(1)}/{short.group(3)}/20{short.group(4)}{value[short.end() :]}"
    return value, offset


def _dayfirst_hint(times: list[str], rows: list[list[str]], skip: int | None) -> bool | None:
    """Whether day/month dates are day first, read from another column of
    the same rows written year first (Tradovate's ``Trade Date``,
    TopstepX's ``TradeDay``)."""
    for column in range(max((len(row) for row in rows), default=0)):
        if column == skip:
            continue
        votes: set[bool] = set()
        for row, text in zip(rows, times, strict=False):
            iso = _ISO_DAY.match(row[column].strip()) if column < len(row) else None
            dmy = _DAY_MONTH.match(text.strip())
            if not iso or not dmy:
                continue
            day, month = int(iso.group(3)), int(iso.group(2))
            first, second = int(dmy.group(1)), int(dmy.group(2))
            if (first, second) == (day, month) and first != second:
                votes.add(True)
            elif (first, second) == (month, day) and first != second:
                votes.add(False)
        if len(votes) == 1:
            return votes.pop()
    # Another day/month column of the file with a day past 12 settles it
    # (Schwab's Closed Date next to its Opened Date).
    for column in range(max((len(row) for row in rows), default=0)):
        for row in rows:
            dmy = _DAY_MONTH.match(row[column].strip()) if column < len(row) else None
            if dmy and int(dmy.group(1)) > 12:
                return True
            if dmy and int(dmy.group(2)) > 12:
                return False
    return None


def _times(
    values: list[str],
    serial: bool,
    rows: list[list[str]] | None = None,
    column: int | None = None,
    date_column: int | None = None,
) -> imp._TimeColumn:
    """A time column; whole-number Unix times (seconds or milliseconds),
    zone suffixes and a clock-only column joined to ``date_column`` too."""
    filled = [value for value in values if value]
    if filled and all(re.fullmatch(r"\d{10}(\d{3})?", value) for value in filled):
        parsed: list[datetime | None] = [
            datetime.fromtimestamp(int(value) / (1000 if len(value) == 13 else 1), tz=UTC)
            if value
            else None
            for value in values
        ]
        return imp._TimeColumn(parsed, False)
    if (
        rows is not None
        and date_column is not None
        and filled
        and all(_CLOCK.match(value.strip()) for value in filled)
    ):
        values = [
            f"{row[date_column].strip() if date_column < len(row) else ''} {value}".strip()
            if value
            else value
            for row, value in zip(rows, values, strict=True)
        ]
    cleaned = [_clean_time(value) for value in values]
    texts = [text for text, _ in cleaned]
    hint = _dayfirst_hint(texts, rows, column) if rows is not None else None
    column_times = imp._parse_times(texts, serial_numbers=serial, dayfirst_hint=hint)
    shifted: list[datetime | None] = []
    zoned = 0
    for moment, (_, offset) in zip(column_times.values, cleaned, strict=True):
        if moment is not None and offset is not None:
            moment -= timedelta(minutes=offset)
            zoned += 1
        shifted.append(moment)
    naive = column_times.naive and zoned < sum(1 for moment in shifted if moment is not None)
    return imp._TimeColumn(shifted, naive)


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
    if word.startswith(("buy", "compra", "youbought", "bought", "cover")):
        return "long"
    if word.startswith(("sell", "vend", "yousold", "sold", "shortsell")):
        return "short"
    return None


#: Quote currencies of exchange pairs (``BTCUSDT``, ``ETH-EUR``), longest first.
_QUOTES = ("FDUSD", "USDT", "USDC", "BUSD", "USD", "EUR", "GBP", "JPY", "TRY", "BRL", "BTC",
           "ETH", "BNB")  # fmt: skip
_UNIT = re.compile(r"[\d.,)\s]([A-Za-z]{2,10})\s*$")


def _paid(
    row: Sequence[str], fees: Sequence[int], decimal: str, symbol: str, coin: str = ""
) -> tuple[float, int]:
    """Costs of one row: every fee column, whatever its sign, as a positive
    sum, and how many fee cells were left out because they are charged in
    another coin than the price (``0.001 BNB`` on ``BTCUSDT``)."""
    paid = 0.0
    other = 0
    plain = re.sub(r"[^A-Z0-9]", "", symbol.upper())
    for index in fees:
        if index >= len(row) or not row[index].strip():
            continue
        found = _UNIT.search(row[index])
        unit = found.group(1).upper() if found else coin.strip().upper()
        amount = abs(_amount(row[index], decimal) or 0.0)
        quote = next((q for q in _QUOTES if plain.endswith(q) and len(plain) > len(q)), "")
        if unit and amount and quote and unit != quote:
            other += 1
            continue
        paid += amount
    return paid, other


def _cell(row: Sequence[str], columns: Mapping[str, int], role: str) -> str:
    index = columns.get(role)
    return row[index] if index is not None and index < len(row) else ""


#: An entry-time column that is really the buy fill's time (Tradovate).
PAIRED_ENTRY_NAMES = frozenset({"boughttimestamp"})

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
FUTURES_WARNING = "futures results computed with each contract's point value: {listed}"
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
    rows = only_fills(header, without_totals(rows))
    if mapping.shape == UNIVERSAL_TRADES_CSV:
        other_coin = _trades(draft, mapping, rows, decimal, serial_dates)
    else:
        other_coin = _fills(draft, mapping, rows, decimal, serial_dates)
    if not draft.trips and chosen:
        _refuse_unreadable_choice(mapping, chosen, rows, decimal, serial_dates)
    if "commission" in mapping.columns or "swap" in mapping.columns:
        draft.itemised = {name for name in ("commission", "swap") if name in mapping.columns}
    if (
        draft.trips
        and draft.itemised
        and not other_coin
        and all(trip.commission == 0 and trip.swap == 0 for trip in draft.trips)
    ):
        draft.warnings.append("every trade has zero commission and fees")
    return draft


#: How a refusal names a role the customer mapped: (English, Spanish).
ROLE_WORDS: dict[str, tuple[str, str]] = {
    "quantity": ("quantity", "cantidad"),
    "entry_time": ("entry time", "hora de entrada"),
    "exit_time": ("exit time", "hora de salida"),
    "time": ("fill time", "hora de la ejecución"),
    "entry_price": ("entry price", "precio de entrada"),
    "exit_price": ("exit price", "precio de salida"),
    "price": ("fill price", "precio de la ejecución"),
    "profit": ("trade result", "resultado de la operación"),
}


def _refuse_unreadable_choice(
    mapping: ColumnMap,
    chosen: Mapping[str, str],
    rows: list[list[str]],
    decimal: str,
    serial: bool,
) -> None:
    """Name the column the customer mapped when it holds nothing readable
    for its role (text chosen as the quantity), instead of the generic
    "no closed trades"."""
    for role, (word_en, word_es) in ROLE_WORDS.items():
        if role not in chosen or role not in mapping.columns:
            continue
        values = [_cell(row, mapping.columns, role) for row in rows]
        if role.endswith("time"):
            times = _times(values, serial, rows, mapping.columns[role], mapping.date_column)
            readable = any(moment is not None for moment in times.values)
            kind_en, kind_es = "dates", "fechas"
        else:
            readable = any(_amount(value, decimal) is not None for value in values)
            kind_en, kind_es = "numbers", "números"
        if readable:
            continue
        name = imp._clip(mapping.names.get(role, chosen[role]), 60)
        raise imp.ReportFormatError(
            "universal_column_unreadable",
            f'the column "{name}" you chose as {word_en} holds no {kind_en}',
            f"la columna «{name}» que elegiste como {word_es} no tiene {kind_es}",
        )


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
) -> int:
    """Read one closed trade per row; returns how many fees were left out
    because they are charged in another coin."""
    columns = mapping.columns
    entry_times = _times(
        [_cell(row, columns, "entry_time") for row in rows], serial, rows, columns["entry_time"]
    )
    exit_times = _times(
        [_cell(row, columns, "exit_time") for row in rows], serial, rows, columns["exit_time"]
    )
    draft.naive_times = entry_times.naive or exit_times.naive
    parsed: list[_Row] = []
    signed = False
    other_coin = 0
    paired = normalise(mapping.names.get("entry_time", "")) in PAIRED_ENTRY_NAMES
    multipliers: list[float] = []
    for position, row in enumerate(rows):
        volume = _amount(_cell(row, columns, "quantity"), decimal)
        entry_price = _amount(_cell(row, columns, "entry_price"), decimal)
        exit_price = _amount(_cell(row, columns, "exit_price"), decimal)
        profit = _amount(_cell(row, columns, "profit"), decimal) if "profit" in columns else None
        entry_time = entry_times.values[position]
        exit_time = exit_times.values[position]
        side = _side(_cell(row, columns, "side")) if "side" in columns else None
        symbol = " ".join(_cell(row, columns, "symbol").split())
        paid, other = _paid(row, mapping.fees, decimal, symbol, _cell(row, columns, "fee_currency"))
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
        if paired:
            # Tradovate pairs a buy fill with a sell fill: whichever came
            # first opened the trade.
            side = "short" if exit_time < entry_time else "long"
            if side == "short":
                entry_time, exit_time = exit_time, entry_time
                entry_price, exit_price = exit_price, entry_price
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
        multipliers.append(_amount(_cell(row, columns, "multiplier"), decimal) or 1.0)
    if other_coin:
        draft.warnings.append(OTHER_COIN_WARNING.format(n=other_coin))
    if "side" not in columns and not paired:
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
                item.paid - item.swap,
            )
            for item in parsed
        ],
        mapping.names.get("profit", ""),
    )
    if net:
        draft.warnings.append(NET_PROFIT_WARNING)
    for item in parsed:
        direction = 1.0 if item.side == "long" else -1.0
        gross = (
            item.profit + (item.paid - item.swap if net else 0.0)
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
    if "profit" in columns:
        return other_coin
    if "multiplier" in columns:
        for trip, factor in zip(draft.trips, multipliers, strict=True):
            trip.gross *= factor
        draft.sized = True
    elif _price_futures(draft, draft.trips):
        draft.sized = True
    else:
        draft.warnings.append(NO_PROFIT_WARNING)
    return other_coin


def _profit_is_net(items: list[tuple[str, float, float | None, float]], column_name: str) -> bool:
    """Whether a profit column already subtracts commission.

    ``items`` are (symbol, price move x quantity, profit, costs: commission
    paid less swap earned).
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
    if abs(as_gross - as_net) > 1e-9 * max(1.0, as_gross):
        return as_net < as_gross

    def roundness(add_back: bool) -> float:
        """How far each symbol's size is from a round contract size."""
        total = 0.0
        for symbol in {item[0] for item in usable}:
            ratios = [
                ((profit or 0.0) + (paid if add_back else 0.0)) / raw
                for name, raw, profit, paid in usable
                if name == symbol
            ]
            size = abs(statistics.median(ratios))
            if size > 0:
                total += abs(size - imp._snap(size)) / size
        return total

    # One trade per symbol fits either reading exactly: the one giving a
    # round size (1, 50, 100 000) wins, else the column's name decides.
    as_gross, as_net = roundness(False), roundness(True)
    if abs(as_gross - as_net) > 1e-6:
        return as_net < as_gross
    return named_net


def _point_value(symbol: str) -> float | None:
    """The CME value per point of a futures contract code (``MNQZ6``,
    ``ES DEC26``); a bare root is not enough, since ``CL`` or ``GC`` alone may
    be a share ticker."""
    code = symbol.strip().upper().split(".")[0]
    root = imp._futures_root(code)
    if root not in imp.FUTURES_POINT_VALUE_USD or code == root:
        return None
    return imp.FUTURES_POINT_VALUE_USD[root]


def _price_futures(draft: imp._Draft, trips: list[imp._Trip]) -> bool:
    """Scale each futures trip's price move by its point value; True when
    every trip was a known contract (so no size is inferred)."""
    priced: dict[str, float] = {}
    for trip in trips:
        value = _point_value(trip.symbol)
        if value is not None:
            trip.gross *= value
            priced[imp._futures_root(trip.symbol.strip().upper().split(".")[0])] = value
    if priced:
        listed = ", ".join(
            f"{root} x{imp._size_text(value)}" for root, value in sorted(priced.items())
        )
        draft.warnings.append(FUTURES_WARNING.format(listed=listed))
    return (
        bool(priced)
        and len(priced) >= 1
        and all(_point_value(trip.symbol) is not None for trip in trips)
    )


def _fills(
    draft: imp._Draft, mapping: ColumnMap, rows: list[list[str]], decimal: str, serial: bool
) -> int:
    """Pair fills first in, first out per account and symbol into round trips;
    returns how many fees were left out because they are charged in another coin.

    A closing fill's own realised profit, when the file has one, is shared
    among the trips it closes by quantity; otherwise the trip's result is the
    price move times quantity times the multiplier column (1 without one).
    """
    columns = mapping.columns
    times = _times(
        [_cell(row, columns, "time") for row in rows],
        serial,
        rows,
        columns["time"],
        mapping.date_column,
    )
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
        symbol = " ".join(_cell(row, columns, "symbol").split())
        paid, other = _paid(row, mapping.fees, decimal, symbol, _cell(row, columns, "fee_currency"))
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
    # A file listed newest first (brokers' activity exports) keeps that order
    # reversed among fills stamped with the same time (a date with no clock).
    newest_first = len(fills) > 1 and fills[0][0] > fills[-1][0]
    if newest_first:
        fills = [(f[0], -f[1], *f[2:]) for f in fills]
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
    if not pairs:
        still_open = sum(1 for lots in open_lots.values() if lots)
    draft.open_positions = still_open
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
    elif "multiplier" in columns or _price_futures(draft, [pair[0] for pair in pairs]):
        draft.sized = True
    else:
        draft.warnings.append(NO_PROFIT_WARNING)
    draft.trips = sorted((pair[0] for pair in pairs), key=lambda t: (t.exit_time, t.entry_time))
    return other_coin


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
