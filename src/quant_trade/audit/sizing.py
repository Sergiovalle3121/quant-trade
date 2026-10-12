"""How much capital a strategy needs, at which size, for a given loss limit.

The question a robot buyer or a copier asks before switching it on: "with my
account, at what size can I run this so that a bad year does not take more
than X % of it?". A backtest answers it only in the currency and lot sizes
it was run with. This section turns the closed trades into that answer.

Method: the net result of each closed trade (after the costs the report
itemises), in money and at the backtest's own sizes. One year of trades is
drawn at random with replacement ``samples`` times, and the deepest fall in
money of each drawn year is recorded. The reference fall is the larger of
the 95th percentile of those falls and the deepest fall the history itself
shows, so a history with one long losing streak is not understated by the
resampling, which breaks streaks.

Two readings follow from the reference fall:

* the capital that keeps it within 10, 20, 30 or 50 % of the account at the
  backtest's own size;
* the share of the backtest's size that keeps it within those limits on the
  backtest's own starting balance.

Assumptions, printed with the section: fixed sizes (no compounding, no size
change after wins or losses), trades independent of one another, the
uploaded costs. It measures the history's losses; it does not say how the
strategy will do.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext
from typing import Any

import numpy as np

from quant_trade.audit.schema import declared, measured, not_measured
from quant_trade.core.models import Trade

#: Loss limits, as a share of the account, the section answers for.
LOSS_LIMITS: tuple[float, ...] = (0.10, 0.20, 0.30, 0.50)
MIN_TRADES = 30
#: Below this span a year drawn from the trades is too much extrapolation to
#: print capital figures a buyer might act on.
MIN_SPAN_DAYS = 90
#: Below one year the section carries a visible warning.
FULL_YEAR_DAYS = 365
#: Trades in a drawn year are kept within these bounds.
MIN_YEAR_TRADES = 20
MAX_YEAR_TRADES = 20_000
MAX_CELLS = 4_000_000
QUANTILE = 95
#: A reference fall below this share of the starting balance is too small to
#: size against: dividing by it prints capitals near zero and sizes in the millions.
MIN_FALL_SHARE = 0.005
#: Size multiples above this print as "more than 10x": past it the history
#: says too little about a bad year for the exact figure to mean anything.
MAX_SIZE_SHARE = 10.0
COPY_MULTIPLIERS = (0.5, 1.0, 2.0, 3.0)
#: A size share or a fall is read to 12 significant digits before it is
#: rounded: 0.3 x (1000 / 3000) is one tenth, not 0.0999999999999999.
SIGNIFICANT = 12

# Kept together so notes in the evidence record have both customer translations.
QUANTITY_NOTES: dict[str, dict[str, str]] = {
    "median": {
        "en": "median trade size in the file's original units",
        "es": "mediana del tamaño de las operaciones en las unidades originales del archivo",
        "pt": "mediana do tamanho das operações nas unidades originais do arquivo",
    },
    "scaled": {
        "en": "median trade size x size share, rounded down to the unit step",
        "es": "mediana del tamaño por fracción del tamaño, "
        "redondeada hacia abajo al paso de la unidad",
        "pt": "mediana do tamanho vezes a fração do tamanho, "
        "arredondada para baixo ao passo da unidade",
    },
    "martingale": {
        "en": "size grows after losses, so a fixed trade size is not measured",
        "es": "el tamaño crece tras las pérdidas, por eso no se mide un tamaño fijo por operación",
        "pt": "o tamanho cresce após perdas, por isso não se mede um tamanho fixo por operação",
    },
    "missing": {
        "en": "the file has no usable trade sizes in its original units",
        "es": "el archivo no tiene tamaños de operación utilizables en sus unidades originales",
        "pt": "o arquivo não tem tamanhos de operação utilizáveis nas unidades originais",
    },
    "share": {
        "en": "no measured size share on the starting balance",
        "es": "no se mide una fracción del tamaño sobre el balance inicial",
        "pt": "não se mede uma fração do tamanho sobre o saldo inicial",
    },
    "copy": {
        "en": "reference fall x copy multiplier / starting balance, with fixed sizes",
        "es": "caída de referencia por multiplicador de copia entre balance inicial, "
        "con tamaños fijos",
        "pt": "queda de referência vezes multiplicador de cópia sobre saldo inicial, "
        "com tamanhos fixos",
    },
    "mixed": {
        "en": "the history mixes instruments traded at different typical sizes, so one size "
        "in the file's units does not apply to all of them",
        "es": "el historial mezcla instrumentos operados con tamaños típicos distintos, por eso "
        "un solo tamaño en las unidades del archivo no sirve para todos",
        "pt": "o histórico mistura instrumentos operados com tamanhos típicos diferentes, por "
        "isso um único tamanho nas unidades do arquivo não serve para todos",
    },
    "above": {
        "en": "the size share is above 10x, so only a lower bound is given: the median trade "
        "size at 10x, rounded down to the unit step",
        "es": "la fracción del tamaño pasa de 10x, por eso solo se da un mínimo: la mediana del "
        "tamaño a 10x, redondeada hacia abajo al paso de la unidad",
        "pt": "a fração do tamanho passa de 10x, por isso só se dá um mínimo: a mediana do "
        "tamanho a 10x, arredondada para baixo ao passo da unidade",
    },
}

_UNIT_NAMES: dict[str, dict[str, str]] = {
    "es": {"lot": "lotes", "contract": "contratos", "file": "unidades del archivo"},
    "en": {"lot": "lots", "contract": "contracts", "file": "file units"},
    "pt": {"lot": "lotes", "contract": "contratos", "file": "unidades do arquivo"},
}
_ONE_CONTRACT = {"es": "1 contrato", "en": "1 contract", "pt": "1 contrato"}
_DOES_NOT_FIT = {
    "es": "no cabe con este límite",
    "en": "does not fit this limit",
    "pt": "não cabe neste limite",
}
_LESS_THAN = {"es": "menos de", "en": "less than", "pt": "menos de"}
_MORE_THAN = {"es": "más de", "en": "more than", "pt": "mais de"}

RESAMPLED_NOTE = (
    "deepest fall in money over one year of trades drawn at random from the history, "
    "at the backtest's sizes"
)
HISTORY_NOTE = "deepest fall in money of the closed trades in their own order"
REFERENCE_NOTE = (
    "the largest of the resampled 95th percentile, the history's own fall and any "
    "drawdown with open trades from the platform or the equity curve"
)
NET_LOSS = (
    "the closed trades end with a net loss, so no size is given for them: at any size the "
    "history loses"
)
PLATFORM_NOTE = "the platform's maximal drawdown in money, open trades included"
CURVE_NOTE = "deepest fall in money of the uploaded equity curve, open trades included"
HIDDEN_LOSSES = (
    "the trades overlap as a grid or with hidden open losses, so closed trades understate "
    "the real fall; upload an equity curve that includes open trades or the platform report "
    "with its equity drawdown"
)
CAPITAL_NOTE = "reference fall / loss limit, at the backtest's sizes"
SCALE_NOTE = "loss limit x starting balance / reference fall"
TINY_FALL_REASON = (
    "the trades show almost no fall to size against: under half a percent of the starting balance"
)
ASSUMPTIONS: dict[str, list[str]] = {
    "es": [
        "Tamaños fijos: sin interés compuesto ni cambios de tamaño tras ganar o perder.",
        "Las operaciones se sortean de forma independiente; la caída del propio historial "
        "cubre las rachas.",
        "Los costos son los que detalla el archivo subido.",
        "Las cifras en dinero van al tamaño que usó el archivo; el tamaño relativo se calcula "
        "sobre su balance inicial, sin sumar depósitos posteriores.",
        "Mide las pérdidas del historial; no es una predicción.",
    ],
    "en": [
        "Fixed sizes: no compounding and no size change after wins or losses.",
        "Trades are drawn independently of one another; the history's own fall covers streaks.",
        "Costs are those the uploaded file itemises.",
        "Money figures are at the sizes the file used; the relative size is computed on its "
        "starting balance, without later deposits.",
        "It measures the history's losses; it is not a forecast.",
    ],
}


def _snap(value: float) -> float:
    """``value`` to ``SIGNIFICANT`` digits, so float noise never crosses a step."""
    return float(f"{value:.{SIGNIFICANT}g}")


def quantity_step(unit: str, median: float | None = None) -> float:
    """The rounding step: 0.01 lot, one contract, and for unnamed file units
    0.01 or, for a median under 0.1 (0.002 BTC), two significant digits of it."""
    if unit == "contract":
        return 1.0
    if unit == "lot" or median is None or not math.isfinite(median) or median <= 0:
        return 0.01
    if median >= 0.1:
        return 0.01
    return float(f"1e{math.floor(math.log10(median)) - 1}")


def _mixed_sizes(values: Sequence[float], instruments: Sequence[str] | None) -> bool:
    """Whether instruments of the history were traded at different typical sizes."""
    if instruments is None or len(instruments) != len(values):
        return False
    groups: dict[str, list[float]] = {}
    for key, value in zip(instruments, values, strict=True):
        groups.setdefault(key, []).append(value)
    if len(groups) < 2:
        return False
    medians = [float(np.median(group)) for group in groups.values()]
    return max(medians) > min(medians) * (1 + 1e-9)


def quantity_profile(
    trades: Sequence[Trade],
    *,
    quantities: Sequence[float] | None = None,
    unit: str = "file",
    martingale: bool = False,
    instruments: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Typical original-file size, never infer lots from economic quantities.

    Importers may multiply ``Trade.quantity`` by a contract's money value.
    Their original volumes must therefore be supplied separately. Raw trade
    CSVs keep their quantity unchanged and use the conservative file unit.
    ``instruments`` (one key per trade, a futures root or the symbol): when
    instruments carry different typical sizes, one median applies to none
    of them (one ES contract against ten MNQ), so no size is measured.
    """
    unit = unit if unit in {"lot", "contract", "file"} else "file"
    values = list(quantities) if quantities is not None else [t.quantity for t in trades]
    reason = None
    if martingale:
        reason = QUANTITY_NOTES["martingale"]["en"]
    elif (
        not values
        or len(values) != len(trades)
        or any(not math.isfinite(value) or value <= 0 for value in values)
        or (quantities is None and unit != "file")
    ):
        reason = QUANTITY_NOTES["missing"]["en"]
    elif _mixed_sizes(values, instruments):
        reason = QUANTITY_NOTES["mixed"]["en"]
    if reason:
        return {
            "unit": unit,
            "median": not_measured(reason),
            "variable": False,
            "martingale": martingale,
        }
    median = float(np.median(values))
    step = quantity_step(unit, median)
    return {
        "unit": unit,
        "median": {**measured(median, QUANTITY_NOTES["median"]["en"]), "step": step},
        "variable": bool(float(np.percentile(values, 90)) > 3 * median),
        "martingale": False,
        "step": step,
    }


def scaled_quantity(
    profile: dict[str, Any],
    share: float | None,
    *,
    strict: bool = False,
    cap: float | None = None,
) -> dict[str, Any]:
    """Round down a typical size; strict excludes a step exactly at the limit.

    The step count is read to nine decimals first, so a float quotient just
    under a step (9.999999999999998 tenths) or just over it counts as that
    step before rounding. Above ``cap`` the share is too far from the
    history for an exact figure: the size at ``cap`` is given, marked
    ``above``, as a lower bound.
    """
    median = profile.get("median") or {}
    if median.get("evidence") != "MEASURED" or median.get("value") is None:
        return not_measured(str(median.get("note") or QUANTITY_NOTES["missing"]["en"]))
    if share is None or not math.isfinite(share) or share < 0:
        return not_measured(QUANTITY_NOTES["share"]["en"])
    unit = str(profile.get("unit") or "file")
    step_value = float(profile.get("step") or quantity_step(unit, float(median["value"])))
    above = cap is not None and share > cap
    used = float(cap) if above and cap is not None else share
    with localcontext() as context:
        context.prec = 60
        step = Decimal(str(step_value))
        steps = (Decimal(str(median["value"])) * Decimal(str(used)) / step).quantize(
            Decimal("1e-9")
        )
        if strict and not above:
            whole = max(Decimal(0), steps.to_integral_value(rounding=ROUND_CEILING) - 1)
        else:
            whole = steps.to_integral_value(rounding=ROUND_FLOOR)
        value = float(whole * step)
    note = QUANTITY_NOTES["above" if above else "scaled"]["en"]
    out = {**measured(value, note), "step": step_value}
    if above:
        out["above"] = True
    return out


def _quantity_number(value: float, unit: str, step: float) -> str:
    if unit == "contract":
        return f"{value:.0f}" if float(value).is_integer() else f"{value:.2f}"
    exponent = Decimal(str(step)).normalize().as_tuple().exponent
    decimals = max(2, -exponent) if isinstance(exponent, int) else 2
    return f"{value:.{decimals}f}"


def quantity_parts(quantity: dict[str, Any], unit: str, locale: str = "en") -> tuple[str, str]:
    """A rounded size in original units, and a remark when not one step fits.

    The first part is short enough for a card's headline: ``0.19 lotes``,
    ``menos de 0.01 lotes`` (with the remark that it does not fit) or
    ``más de 2.90 lotes`` for a size share above the cap.
    """
    value = quantity.get("value")
    if quantity.get("evidence") != "MEASURED" or value is None:
        return "—", ""
    lang = locale if locale in _UNIT_NAMES else "en"
    names = _UNIT_NAMES[lang]
    unit = unit if unit in names else "file"
    step = float(quantity.get("step") or quantity_step(unit))

    def amount(number: float) -> str:
        if unit == "contract" and number == 1:
            return _ONE_CONTRACT[lang]
        return f"{_quantity_number(number, unit, step)} {names[unit]}"

    if value == 0:
        return f"{_LESS_THAN[lang]} {amount(step)}", _DOES_NOT_FIT[lang]
    if quantity.get("above"):
        return f"{_MORE_THAN[lang]} {amount(float(value))}", ""
    return amount(float(value)), ""


def quantity_text(quantity: dict[str, Any], unit: str, locale: str = "en") -> str:
    """:func:`quantity_parts` on one line: ``menos de 0.01 lotes (no cabe ...)``."""
    head, remark = quantity_parts(quantity, unit, locale)
    return f"{head} ({remark})" if remark else head


def copy_fall_text(row: dict[str, Any], locale: str = "en") -> str:
    """Linear money fall relative to the provider's starting balance.

    Rounded down to a tenth of a percent, so 99.985 % never reads as the
    100.0 % at which the entire account is lost.
    """
    value = (row.get("fall_pct") or {}).get("value")
    if value is None:
        return "—"
    tenths = math.floor(Decimal(str(_snap(float(value)))) * 1000)
    text = f"{tenths / 10:.1f}%"
    if row.get("account_lost"):
        notice = {
            "es": "pierde la cuenta entera",
            "en": "loses the entire account",
            "pt": "perde a conta inteira",
        }.get(locale, "loses the entire account")
        text += f" · {notice}"
    return text


def _deepest_fall(pnl: np.ndarray) -> np.ndarray:
    """Deepest peak-to-trough fall in money of each row of cumulative results."""
    path = np.cumsum(pnl, axis=-1)
    start = np.zeros((*path.shape[:-1], 1))
    path = np.concatenate([start, path], axis=-1)
    return np.max(np.maximum.accumulate(path, axis=-1) - path, axis=-1)


def capital_review(
    trades: Sequence[Trade],
    *,
    fees: Sequence[float] | None,
    starting_balance: float | None,
    platform_fall: float | None = None,
    curve_fall: float | None = None,
    hidden_open_losses: bool = False,
    quantities: Sequence[float] | None = None,
    quantity_unit: str = "file",
    martingale: bool = False,
    instruments: Sequence[str] | None = None,
    profile: dict[str, Any] | None = None,
    samples: int = 2000,
    seed: int = 0,
) -> dict[str, Any]:
    """Capital and size for each loss limit, from the closed trades.

    ``platform_fall`` and ``curve_fall`` are falls in money that include open
    trades; either is a floor for the reference fall. With
    ``hidden_open_losses`` (a grid, or positions overlapping on a curve rebuilt
    from closed trades) and neither floor, the figures are held back: a grid
    closes its baskets in profit and the closed trades hide its real fall.
    ``profile`` is a :func:`quantity_profile` the caller already built;
    without it one is built from ``quantities`` and the arguments after it.
    """
    platform = platform_fall if platform_fall is not None and platform_fall > 0 else None
    curve = curve_fall if curve_fall is not None and curve_fall > 0 else None
    if hidden_open_losses and platform is None and curve is None:
        return {"status": "NOT_MEASURED", "reason": HIDDEN_LOSSES}
    if len(trades) < MIN_TRADES:
        return {
            "status": "NOT_MEASURED",
            "reason": f"needs at least {MIN_TRADES} closed trades; {len(trades)} supplied",
        }
    ordered = sorted(range(len(trades)), key=lambda i: trades[i].exit_time)
    costs = list(fees) if fees is not None else [0.0] * len(trades)
    pnl = np.array([trades[i].pnl - costs[i] for i in ordered], dtype=float)
    if float(pnl.sum()) <= 0:
        return {"status": "NOT_MEASURED", "reason": NET_LOSS}
    first = min(trade.entry_time for trade in trades)
    last = max(trade.exit_time for trade in trades)
    span_days = (last - first).total_seconds() / 86_400
    if span_days < MIN_SPAN_DAYS:
        return {
            "status": "NOT_MEASURED",
            "reason": f"needs trades spread over at least {MIN_SPAN_DAYS} days; a shorter "
            "history stretched to a year gives capital figures too uncertain to act on",
        }
    per_year = int(round(len(pnl) * 365.25 / span_days))
    per_year = min(max(per_year, MIN_YEAR_TRADES), MAX_YEAR_TRADES)
    used = int(max(100, min(samples, MAX_CELLS // per_year)))
    rng = np.random.default_rng(seed)
    drawn = pnl[rng.integers(0, len(pnl), size=(used, per_year))]
    falls = _deepest_fall(drawn)
    history = float(_deepest_fall(pnl))
    resampled = float(np.percentile(falls, QUANTILE))
    reference = max(resampled, history, platform or 0.0, curve or 0.0)
    if not math.isfinite(reference) or reference <= 0:
        return {"status": "NOT_MEASURED", "reason": "the trades show no fall to size against"}

    balance = (
        starting_balance
        if starting_balance and math.isfinite(starting_balance) and starting_balance > 0
        else None
    )
    if balance is not None and reference < MIN_FALL_SHARE * balance:
        return {"status": "NOT_MEASURED", "reason": TINY_FALL_REASON}
    if profile is None:
        profile = quantity_profile(
            trades,
            quantities=quantities,
            unit=quantity_unit,
            martingale=martingale,
            instruments=instruments,
        )
    rows = []
    for limit in LOSS_LIMITS:
        rows.append(
            {
                "limit": limit,
                "capital": measured(reference / limit, CAPITAL_NOTE),
                "size_share": (
                    measured(limit * balance / reference, SCALE_NOTE)
                    if balance
                    else not_measured("the file states no starting balance")
                ),
                # Past MAX_SIZE_SHARE the share reads "more than 10x"; the
                # quantity is then a lower bound, never the exact figure.
                "quantity": scaled_quantity(
                    profile,
                    limit * balance / reference if balance else None,
                    cap=MAX_SIZE_SHARE,
                ),
            }
        )
    return {
        "status": "MEASURED",
        "trades_per_year": measured(
            per_year,
            "closed trades per year in the history"
            if span_days >= FULL_YEAR_DAYS
            else "closed trades per year at the history's pace; the history is shorter than a year",
        ),
        "fall_p50": measured(float(np.percentile(falls, 50)), RESAMPLED_NOTE),
        "fall_p95": measured(resampled, RESAMPLED_NOTE),
        "fall_history": measured(history, HISTORY_NOTE),
        "fall_platform": (
            declared(platform, PLATFORM_NOTE)
            if platform is not None
            else not_measured("the file does not print the platform's drawdown in money")
        ),
        "fall_curve": (
            measured(curve, CURVE_NOTE)
            if curve is not None
            else not_measured("no equity curve with open trades in money")
        ),
        "short_history": span_days < FULL_YEAR_DAYS,
        "span_days": measured(round(span_days), "days from the first entry to the last exit"),
        "fall_reference": measured(reference, REFERENCE_NOTE),
        "starting_balance": (
            declared(balance, "starting balance of the uploaded file")
            if balance
            else not_measured("the file states no starting balance")
        ),
        "rows": rows,
        "quantity_profile": profile,
        "copy_rows": [
            {
                "multiplier": multiplier,
                "fall_pct": (
                    measured(reference * multiplier / balance, QUANTITY_NOTES["copy"]["en"])
                    if balance
                    else not_measured("the file states no starting balance")
                ),
                "account_lost": bool(balance and _snap(reference * multiplier / balance) >= 1),
            }
            for multiplier in COPY_MULTIPLIERS
        ],
        "method": {"samples": used, "seed": int(seed), "quantile": QUANTILE},
        "assumptions": ASSUMPTIONS,
    }


def scale_text(share: float, locale: str = "en") -> str:
    """A size share as a reader says it: ``0.35x``, ``2.0x`` or ``more than 10x``."""
    if not math.isfinite(share):
        return "—"
    if share > MAX_SIZE_SHARE:
        prefix = {"es": "más de", "pt": "mais de"}.get(locale, "more than")
        return f"{prefix} {MAX_SIZE_SHARE:g}x"
    return f"{share:.2f}x" if share < 1 else f"{share:.1f}x"


__all__ = [
    "ASSUMPTIONS",
    "COPY_MULTIPLIERS",
    "FULL_YEAR_DAYS",
    "LOSS_LIMITS",
    "MAX_SIZE_SHARE",
    "MIN_FALL_SHARE",
    "MIN_SPAN_DAYS",
    "MIN_TRADES",
    "QUANTITY_NOTES",
    "capital_review",
    "copy_fall_text",
    "quantity_parts",
    "quantity_profile",
    "quantity_step",
    "quantity_text",
    "scale_text",
    "scaled_quantity",
]
