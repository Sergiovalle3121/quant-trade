"""File quantities below the selected challenge's daily loss limit.

This is a replay of daily closes at fixed sizes, on the history's starting
balance. It is independent of the challenge simulation and the verdict.
For an initial-balance rule the bound is limit * initial balance / worst
daily money loss. For a start-of-day rule, the scaled day's opening balance
is initial + scale * (historical opening - initial), so each day imposes
scale * (loss - limit * historical cumulative gain) < limit * initial.
The tightest bound is rounded strictly downward in the file's units.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.audit.prop_presets import ChallengeRules
from quant_trade.audit.schema import declared, measured
from quant_trade.audit.sizing import scaled_quantity

DAILY_NOTE = (
    "daily closes on the history's starting balance, with fixed sizes; the rounded size "
    "stays below the daily limit on this path; intraday losses and the total-loss rule "
    "are not covered"
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

# New evidence notes and reasons retain explicit Spanish and Portuguese rules.
TRANSLATIONS: dict[str, dict[str, str]] = {
    "es": {
        DAILY_NOTE: "Cierres diarios sobre el balance inicial del historial, con tamaños fijos; "
        "el tamaño redondeado queda por debajo del límite diario en este recorrido; no cubre "
        "pérdidas intradía ni la regla de pérdida total.",
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
    },
    "pt": {
        DAILY_NOTE: "Fechamentos diários sobre o saldo inicial do histórico, com tamanhos fixos; "
        "o tamanho arredondado fica abaixo do limite diário neste percurso; não cobre perdas "
        "intradiárias nem a regra de perda total.",
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
    },
}


def daily_limit_review(
    frame: pd.DataFrame,
    rules: ChallengeRules,
    profile: dict[str, Any],
    balance: dict[str, Any],
) -> dict[str, Any]:
    """The largest file quantity strictly below the daily rule on this path.

    Daily closes and UTC day boundaries match ``daily_returns_from_equity``.
    The first day's opening is the known starting balance: unlike percentage
    changes between closes, this also counts losses before the first close.
    The size is on the uploaded history's balance, not a different account
    named by a preset. A zero rounded quantity is measured and rendered as
    too small to fit; an unknown balance or quantity is never substituted.
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
    if median.get("evidence") != "MEASURED":
        return missing(str(median.get("note") or NO_CURVE))
    initial = balance.get("value")
    if (
        balance.get("evidence") not in {"MEASURED", "DECLARED"}
        or not isinstance(initial, int | float)
        or not math.isfinite(initial)
        or initial <= 0
    ):
        return missing(NO_BALANCE)
    stamps = pd.to_datetime(frame["timestamp"], utc=True)
    equity = pd.Series(frame["equity"].to_numpy(dtype=float), index=stamps)
    closes = equity.groupby(stamps.dt.floor("D").to_numpy()).last().to_numpy(dtype=float)
    if len(closes) < 2 or not np.all(np.isfinite(closes)) or np.any(closes <= 0):
        return missing(NO_CURVE)
    openings = np.concatenate(([initial], closes[:-1]))
    losses = openings - closes
    worst = float(np.max(losses))
    if worst <= 0:
        return missing(NO_LOSS)
    limit = rules.max_daily_loss
    divisor = worst
    if rules.daily_loss_basis == "start_of_day":
        divisor = float(np.max(losses - limit * (openings - initial)))
    if divisor <= 0 or not math.isfinite(divisor):
        return missing(NO_BOUND)
    share = limit * initial / divisor
    if not math.isfinite(share):
        return missing(NO_BOUND)
    return {
        **base,
        "status": "MEASURED",
        "starting_balance": balance,
        "daily_limit": declared(limit, LIMIT_NOTE),
        "worst_day_loss": measured(worst, WORST_DAY_NOTE),
        "size_share": measured(share, SCALE_NOTE),
        # A float quotient can land just above an exact lot/contract step.
        # Move one ULP inward before applying the strict decimal rounding.
        "quantity": scaled_quantity(profile, math.nextafter(share, 0.0), strict=True),
    }
