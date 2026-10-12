"""File quantities below the selected challenge's daily loss limit.

A replay of the history's daily closes at fixed sizes. It does not use the
challenge simulation and does not feed the verdict. The money the daily rule
allows is its limit times the balance the size is given on: the account a
program states its dollar limits on (``prop_presets.ACCOUNT_SIZES``) when it
names one, otherwise the history's own starting balance. For an
initial-balance rule the bound is limit * that balance / worst daily money
loss. For a start-of-day rule, the scaled day's opening balance is
balance + scale * (historical opening - historical initial), so each day
imposes scale * (loss - limit * historical cumulative gain) < limit * balance.
The tightest bound is rounded strictly downward in the file's units.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.audit.analytics import daily_closes
from quant_trade.audit.prop_presets import ChallengeRules
from quant_trade.audit.schema import DECLARED, MEASURED, declared, measured
from quant_trade.audit.sizing import (
    MAX_SIZE_SHARE,
    MIN_FALL_SHARE,
    QUANTITY_NOTES,
    scaled_quantity,
)

DAILY_NOTE = (
    "Daily closes of the history at fixed sizes, scaled to the balance shown; the rounded "
    "size stays below the daily limit on this path. Intraday losses and the total-loss rule "
    "are not covered."
)
WORST_DAY_NOTE = (
    "largest daily closing loss in money, including the first day from the starting balance"
)
LIMIT_NOTE = "daily loss limit in the selected firm's dated rules"
SCALE_NOTE = "upper size bound from daily closes and the selected daily loss basis"
NO_LIMIT = "the selected rules have no daily loss limit to size against"
NO_BALANCE = "the starting balance is not known, so the daily-limit size is not measured"
NO_LOSS = "the daily closes show no losing day to size against"
NO_CURVE = "the daily-limit size needs at least two finite positive daily closes"
NO_BOUND = "the daily loss rule gives no finite upper size bound on this path"
TINY_LOSS = (
    "the largest daily loss is under half a percent of the starting balance, too small "
    "to size against"
)

# New evidence notes and reasons retain explicit Spanish and Portuguese rules.
TRANSLATIONS: dict[str, dict[str, str]] = {
    "es": {
        DAILY_NOTE: "Cierres diarios del historial con tamaños fijos, escalados al balance "
        "indicado; el tamaño redondeado queda por debajo del límite diario en este recorrido. "
        "No cubre pérdidas intradía ni la regla de pérdida total.",
        WORST_DAY_NOTE: "mayor pérdida diaria en dinero al cierre, incluido el primer día "
        "desde el balance inicial",
        LIMIT_NOTE: "límite de pérdida diaria en las reglas fechadas de la firma elegida",
        SCALE_NOTE: "cota superior de tamaño según los cierres diarios "
        "y la base del límite elegido",
        NO_LIMIT: "las reglas elegidas no tienen un límite de pérdida diaria "
        "para calcular el tamaño",
        NO_BALANCE: "no se conoce el balance inicial, por lo que no se mide "
        "el tamaño por límite diario",
        NO_LOSS: "los cierres diarios no muestran un día con pérdida para calcular el tamaño",
        NO_CURVE: "el tamaño por límite diario necesita al menos dos cierres "
        "diarios positivos y finitos",
        NO_BOUND: "la regla de pérdida diaria no da una cota superior finita "
        "de tamaño en este recorrido",
        TINY_LOSS: "la mayor pérdida diaria es menor que medio por ciento del balance "
        "inicial, demasiado pequeña para calcular el tamaño",
    },
    "pt": {
        DAILY_NOTE: "Fechamentos diários do histórico com tamanhos fixos, escalados ao saldo "
        "indicado; o tamanho arredondado fica abaixo do limite diário neste percurso. "
        "Não cobre perdas intradiárias nem a regra de perda total.",
        WORST_DAY_NOTE: "maior perda diária em dinheiro no fechamento, incluindo o primeiro dia "
        "a partir do saldo inicial",
        LIMIT_NOTE: "limite de perda diária nas regras datadas da empresa escolhida",
        SCALE_NOTE: "limite superior de tamanho pelos fechamentos diários "
        "e pela base do limite escolhido",
        NO_LIMIT: "as regras escolhidas não têm limite de perda diária para calcular o tamanho",
        NO_BALANCE: "o saldo inicial é desconhecido, por isso o tamanho "
        "pelo limite diário não é medido",
        NO_LOSS: "os fechamentos diários não mostram um dia de perda para calcular o tamanho",
        NO_CURVE: "o tamanho pelo limite diário precisa de pelo menos dois "
        "fechamentos diários positivos e finitos",
        NO_BOUND: "a regra de perda diária não dá um limite superior finito "
        "de tamanho neste percurso",
        TINY_LOSS: "a maior perda diária é menor que meio por cento do saldo inicial, "
        "pequena demais para calcular o tamanho",
    },
}


def _positive(record: dict[str, Any] | None, evidence: set[str]) -> float | None:
    value = (record or {}).get("value")
    if (
        (record or {}).get("evidence") not in evidence
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or value <= 0
    ):
        return None
    return float(value)


def daily_limit_review(
    frame: pd.DataFrame,
    rules: ChallengeRules,
    profile: dict[str, Any],
    balance: dict[str, Any],
    *,
    account: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The largest file quantity strictly below the daily rule on this path.

    Daily closes and UTC day boundaries match ``daily_returns_from_equity``.
    The first day's opening is the known starting balance: unlike percentage
    changes between closes, this also counts losses before the first close.
    ``account`` (DECLARED, the account a program states its dollar limits
    on) is the balance the size is given on; without it, the history's own
    ``balance``. ``basis`` and ``sized_on`` say which. A zero rounded quantity
    is measured and rendered as too small to fit; an unknown balance or
    quantity is never substituted. A share above ``MAX_SIZE_SHARE`` times
    the history's own size on its balance is given only as a lower bound.
    """
    base: dict[str, Any] = {
        "unit": profile.get("unit", "file"),
        "quantity_profile": profile,
        "note": DAILY_NOTE,
    }

    def missing(reason: str) -> dict[str, Any]:
        return {**base, "status": "NOT_MEASURED", "reason": reason}

    if rules.max_daily_loss is None:
        return missing(NO_LIMIT)
    median = profile.get("median") or {}
    if median.get("evidence") != MEASURED:
        return missing(str(median.get("note") or QUANTITY_NOTES["missing"]["en"]))
    initial = _positive(balance, {MEASURED, DECLARED})
    if initial is None:
        return missing(NO_BALANCE)
    closes = daily_closes(frame).to_numpy(dtype=float)
    if len(closes) < 2 or not np.all(np.isfinite(closes)) or np.any(closes <= 0):
        return missing(NO_CURVE)
    openings = np.concatenate(([initial], closes[:-1]))
    losses = openings - closes
    worst = float(np.max(losses))
    if worst <= 0:
        return missing(NO_LOSS)
    if worst < MIN_FALL_SHARE * initial:
        # Dividing by an almost-zero loss prints sizes in the hundreds of times.
        return missing(TINY_LOSS)
    limit = rules.max_daily_loss
    divisor = worst
    if rules.daily_loss_basis == "start_of_day":
        divisor = float(np.max(losses - limit * (openings - initial)))
    if divisor <= 0 or not math.isfinite(divisor):
        return missing(NO_BOUND)
    on_account = _positive(account, {DECLARED})
    sized_on = account if on_account is not None and account is not None else balance
    money = on_account if on_account is not None else initial
    share = limit * money / divisor
    if not math.isfinite(share):
        return missing(NO_BOUND)
    return {
        **base,
        "status": "MEASURED",
        "starting_balance": balance,
        "basis": "account" if on_account is not None else "history",
        "sized_on": sized_on,
        "daily_limit": declared(limit, LIMIT_NOTE),
        "worst_day_loss": measured(worst, WORST_DAY_NOTE),
        "size_share": measured(share, SCALE_NOTE),
        "quantity": scaled_quantity(
            profile, share, strict=True, cap=MAX_SIZE_SHARE * money / initial
        ),
    }
