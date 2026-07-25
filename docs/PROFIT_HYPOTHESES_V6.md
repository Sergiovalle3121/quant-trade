# Pre-registered Profit Hypotheses — V6 (Economic Integrity)

Registered: 2026-07-25T03:30Z, at commit `1232918`, BEFORE any V6 campaign
ran on real data. This supersedes `PROFIT_HYPOTHESES_V5.md` where noted; all
V5 binding rules (no holdout tuning, no lowered gates, every trial counted,
PAPER_CANDIDATE max, synthetic/fixture never promotable) remain in force.

## What changed from V5 (and why it is stricter, never looser)

1. **Signal semantics made exact (V6-H).** H1/H2 signals consume the
   SETTLEMENT-HELD series: each bar's signal value is the most recent settled
   rate known at that bar, held constant between settlements; the entry rule
   is the trailing mean over that series (duration-weighted mean of recent
   settled rates). Polls carry zero entry authority; zero settlements means
   zero signal.
2. **H3 re-registered as what it claims to be (V6-I):** perp-perp
   cross-venue funding dispersion — long the lower-funding perp, short the
   higher, settled-spread trailing signal, per-venue marks and collateral,
   switching + transfer costs, terminal close. Requires BOTH venue panels;
   promotion additionally requires beating max(H1, H2, cash).
3. **Provenance is receipt-verified (V6-D).** A campaign is "real" only when
   every record traces to a byte-verified live ingestion receipt. Mixed,
   unverified, or fixture provenance terminates at NOT_RUN.
4. **The ledger is the only P&L (V6-A).** All hypotheses are evaluated by the
   reconciled balance-sheet ledger; the diagnostic aggregate can never
   promote anything.

## Statistical gates (fixed; executed, not documented — V6-J)

- PSR ≥ 0.95 · DSR ≥ 0.95 (conservative trial counting from the ledger)
- PBO (walk-forward negative-window fraction) ≤ 0.50, needing ≥ 4 windows
- bootstrap lower bound > 0 · majority OOS windows positive
- positive at 2× costs (full stack incl. venue taker fee), 3× reported
- zero liquidations · reconciled ledger · byte-reproduced promotion
- sufficiency counts UNIQUE SETTLEMENTS, never polls or bars

## Datasets registered for V6

| Dataset | Rule |
|---|---|
| `data/carry/panel/<venue>_<base>/` (HistoricalCarryPanel) | the ONLY promotable source once built from live receipts |
| jsonl collector stores with receipts | usable; settlement-driven signals |
| recorded-response fixtures (`tests/fixtures/`) | TEST_ONLY forever |
| any dataset without receipts | `unverified_legacy`, never promotable |

## Environment fact recorded at registration

Outbound HTTPS to `api.bybit.com` / `www.okx.com` still fails from this
sandbox with proxy `403 Forbidden` (verbatim in the committed
`backfill_attempts.jsonl` logs). Until the network policy changes, every
live campaign remains NOT_RUN and the pipeline is proven end-to-end on
recorded responses marked TEST_ONLY.
