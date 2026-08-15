# SPY turn-of-month campaign

Status: **SEALED RESEARCH DESIGN — NO PERFORMANCE EVIDENCE — NEVER LIVE**

`SPY_TOM_Dm1_P3_v1` is one isolated falsification campaign for a fractional
SPY turn-of-month target. It does not read prices, historical returns, a
holdout, keys, the strategy registry, or the network. It cannot route even a
paper order. Its only output is a non-executable target intention carrying
`real_money_authorized=false` and a verdict ceiling of
`INSUFFICIENT_EVIDENCE`.

The canonical declaration is
`configs/experiments/spy_tom_dm1_p3_v1.yaml`. Its SHA-256 content seal is:

```text
5d2c57f22a4437b3064a596b3dd804c7e1e683b3228d4a5d6901e73f1053c540
```

The seal detects changes to every policy field. The Python constructor also
rejects a re-sealed alternative rule, and each generated target revalidates
the full specification. This is local content addressing, not an independent
timestamp or proof that the declaration predates any earlier analysis.

## External motivation and translation risk

McConnell and Xu report concentration of U.S. equity returns in the four-day
turn-of-month interval over 1926–2005 in
[*Equity Returns at the Turn of the Month*](https://rpc.cfainstitute.org/research/financial-analysts-journal/2008/equity-returns-at-the-turn-of-the-month),
*Financial Analysts Journal* 64(2), 49–64,
[doi:10.2469/faj.v64.n2.11](https://doi.org/10.2469/faj.v64.n2.11).

This campaign is **not an exact replication**. It substitutes SPY for the
paper's market series, uses a fractional US$195 target, samples an intraday
execution window, and compares the result with a paired control. Publication
of the anomaly is motivation for a test, not evidence that it persists after
costs or that SPY can earn the published return.

## Frozen rule

The paper sleeve starts with US$200 of simulated capital:

- maximum gross SPY exposure: US$195;
- minimum cash reserve: US$5;
- SPY only, fractional, long or cash;
- no leverage, shorting, options, stops, dynamic parameters, or averaging;
- one trial; no parameter search after seeing results.

For each pair of adjacent, explicitly completed XNYS calendar months:

| Leg | Entry observation | Exit observation | Exposure intervals |
|---|---|---|---:|
| Primary | 15:55 ET on the penultimate session of month M | 15:55 ET on session 3 of M+1 | 4 |
| Paired control | 15:55 ET on session 8 of M+1 | 15:55 ET on session 12 of M+1 | 4 |

An exact 15:55 observation creates a target no earlier than 15:56, and the
target expires at 15:58 ET. Same-bar execution is forbidden. If the exact
observation is absent, the generator emits nothing: it does not use 15:54,
15:56, the previous session, or the next session as a fallback.

The control is paired by following calendar month and holds for the same four
session-to-session intervals. The intended causal comparison is primary minus
control, not primary return in isolation.

## Calendar and causality boundary

`ExplicitExchangeCalendar` consumes caller-supplied open and close timestamps
for every session in consecutive months declared complete. It validates
ordering, uniqueness, weekdays, month coverage, 09:30 opens, 13:00/16:00
closes, and minimum length using the IANA `America/New_York` timezone.
Therefore DST offsets are not fixed and holidays remain absent exactly as
supplied. If any of a pair's four required sessions closes before 15:58, the
**entire pair is excluded**; an early-close exit can never disappear while its
entry survives.

The class is only a **caller attestation**. It does not prove that the schedule
came from Alpaca or XNYS and cannot detect a plausible-looking omitted weekday
or fabricated close. An authoritative calendar export, acquisition receipt, byte hash,
source identifier, and retrieval timestamp remain required evidence. Until
those exist, calendar authenticity is an explicit blocker and no economic
result may clear `INSUFFICIENT_EVIDENCE`.

The generator accepts only timestamps already observable at an aware `as_of`.
Future observations are rejected. Appending later observations cannot change
prior intentions, provided the same predeclared complete calendar is used.
The calendar is scheduling metadata fixed before observation; it is not
silently extended or repaired by this module.

## Evidence and stopping rule

Evaluation requires at least **120 complete paired months** under the one
frozen rule. Every historical price, quote, spread, fill, or calendar sample
ever inspected is classified as **development data only**. It is not a hidden
or out-of-sample holdout, even if it was not used by the target generator.

Evaluation must use total returns. A content-addressed, point-in-time corporate
action ledger must credit cash dividends when the position is held at the
ex-date open and adjust quantity for stock splits at the effective session
open. Missing dividend, split, revision, receipt, or ledger-hash evidence makes
the result `INSUFFICIENT_EVIDENCE`; price-only SPY returns are prohibited.

The only permitted campaign verdicts are `NO_GO` and
`INSUFFICIENT_EVIDENCE`. `PASS` is structurally prohibited. Paper gains do not
authorize live trading, a deposit, a bank transfer, or a claim of expected
profit. A separate prospective observation period and the repository's full
risk, cost, broker, and governance gates would still be required.

The current development-bundle schema is more restrictive: because its
manifest and receipt claims have no provider signature or allowlisted external
trust root, it can emit only `INSUFFICIENT_EVIDENCE`. Its metrics are diagnostic
and cannot yet establish an authoritative `NO_GO` either.

## Pure API

```python
generate_spy_tom_targets(
    spec: SpyTomSpec,
    calendar: ExplicitExchangeCalendar,
    observable_timestamps: Sequence[datetime],
    *,
    as_of: datetime,
) -> tuple[TargetIntention, ...]
```

There is intentionally no price argument, broker object, secret, network
session, generic runner, registry hook, P&L calculation, or execution method.
