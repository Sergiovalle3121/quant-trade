# Runbook: the low/mid-cap crypto campaign, end to end, on your machine

Session C. Everything below is research-only: no orders, no funds, no keys.
Every command fails closed, and nothing here can be made to pass by editing a
threshold after the fact, because every threshold is sealed before the data is
read and locked on first use.

This sandbox cannot run the campaign: the venues and CoinMarketCap refuse its
egress at CONNECT (`403`), and the 15 GB dataset is git-ignored. The code is
built and tested against fixtures; the numbers come from your machine.

## 0. What you need

- the point-in-time universe under `data/cache/crypto_universe/v1`
  (4,852 daily snapshots, journal chain intact);
- the death list under `data/cache/crypto_universe/deathlist`;
- venue klines under `data/cache/venue_klines/bybit` and
  `data/cache/venue_klines/binance` (adjust `--venue-dir` if yours differ);
- the built panel `data/experiments/crypto_lowcap_2026_08/panel.csv.gz`
  (895,760 rows, 893 symbols) whose digest is `e25722f1…`.

If any of these is missing, go to §5 first.

```bash
python -m pip install -e ".[dev,crypto]"
```

## 1. Verify the panel against the seal (fails closed)

The seal is bound to bytes, not dates. The first seal recorded its component
hashes without saying how they were computed, so verification **probes** the
declared candidate recipes and reports which one reproduces each hash. Every
component must be reproduced or the seal is unverifiable here.

```bash
quant-trade crypto-lowcap verify-panel \
  --experiment-dir data/experiments/crypto_lowcap_2026_08 \
  --panel data/experiments/crypto_lowcap_2026_08/panel.csv.gz \
  --universe-dir data/cache/crypto_universe/v1 \
  --deathlist-dir data/cache/crypto_universe/deathlist \
  --venue-dir bybit=data/cache/venue_klines/bybit \
  --venue-dir binance=data/cache/venue_klines/binance \
  --explain
```

`PASS` writes `panel_verification.json`, which binds the campaign to the
verified panel's content hash. `FAIL` prints, per component, every recipe
hash that was tried. Two outcomes are possible on a `FAIL`:

- one component's bytes changed since sealing: fix the dataset, do not touch
  the seal;
- no recipe reproduces the recorded hash: the first seal cannot be verified
  from these bytes. Do not evaluate against it. Go to §5 and reseal.

## 2. Run the selection campaign (once)

```bash
quant-trade crypto-lowcap select \
  --experiment-dir data/experiments/crypto_lowcap_2026_08 \
  --trials configs/research/crypto_lowcap_trials.yaml \
  --panel data/experiments/crypto_lowcap_2026_08/panel.csv.gz
```

What it does, in order: refuses if the holdout was ever revealed; refuses if
`SELECTION_RESULTS.json` exists (a second run would spend the declared budget
twice); locks the trials file, the gate files and the panel hash in
`campaign_lock.json`; slices the panel to the selection window and asserts
every date is inside it; runs the 19 declared trials of H1–H5 with their
sealed controls at delisting recovery 1.0 and 0.0 and at 1x/2x/3x costs;
walks forward over 2019–2023 with a 90-day embargo; appends one sealed record
per trial to `trial_ledger.jsonl`; scores every trial under its primary gate
and under the unmodified ETF gate; freezes at most one primary candidate (and
at most one secondary per other hypothesis) in `frozen_selection.json`.

Runtime on the full panel: minutes to a few tens of minutes, single process.

Read `selection/SELECTION_RESULTS.json` before going on. If `frozen.primary`
is `null`, the programme's answer is "no candidate", the holdout stays sealed,
and §3 will say so without reading it.

## 3. Reveal the holdout (exactly once)

```bash
quant-trade crypto-lowcap reveal \
  --experiment-dir data/experiments/crypto_lowcap_2026_08 \
  --panel data/experiments/crypto_lowcap_2026_08/panel.csv.gz \
  --reason "final evaluation of the frozen candidates"
```

The reveal record is appended to `holdout_reveals.jsonl` **before** the panel
is loaded; a second call raises. Only the frozen candidates, their sealed
controls and the declared benchmarks are evaluated over 2023-11-29 →
2026-08-09. The verdict in `holdout/HOLDOUT_VERDICT.json` is a range: the
seal declares that 2.69 years cannot separate a true annualised Sharpe of 1.0
from zero, so each candidate carries its standard error and a class of
`RANGE_ABOVE_ZERO`, `RANGE_INCLUDES_ZERO` or `RANGE_BELOW_ZERO`.

## 4. Render and commit

```bash
quant-trade crypto-lowcap report \
  --experiment-dir data/experiments/crypto_lowcap_2026_08 \
  --output docs/CRYPTO_LOWCAP_RESULTS.md
git add data/experiments/crypto_lowcap_2026_08/{campaign_lock.json,panel_verification.json,trial_ledger.jsonl,frozen_selection.json,holdout_reveals.jsonl,selection,holdout} docs/CRYPTO_LOWCAP_RESULTS.md
```

The report refuses to render if it contains profit-claim language. The panel
itself stays git-ignored.

## 5. If the dataset is missing, or the digest does not reproduce

Re-collect with the existing collectors (the calls are in
`docs/CRYPTO_LOWCAP_DATASET.md` § Reproduction; roughly two hours for the
universe, less for the venues), rebuild the panel with
`quant_trade.data.crypto_panel.build_panel`, then write a digest that
**declares its recipe** and seal a new experiment:

```bash
quant-trade crypto-lowcap panel-digest \
  --experiment-dir data/experiments/crypto_lowcap_2026_09 \
  --panel data/experiments/crypto_lowcap_2026_09/panel.csv.gz \
  --build-report data/experiments/crypto_lowcap_2026_09/panel_build_report.json
quant-trade crypto-lowcap reseal \
  --from-dir data/experiments/crypto_lowcap_2026_08 \
  --to-dir data/experiments/crypto_lowcap_2026_09 \
  --panel data/experiments/crypto_lowcap_2026_09/panel.csv.gz
```

`reseal` clones the five pre-registrations verbatim except for the digest
they bind to, seals a new 70/30 holdout, and refuses an existing target. The
old seal is never edited: a different dataset is a different experiment with
its own budget. Then run §1–§4 against the new directory.

## 6. H6: trend following on crypto majors (separate dataset, same discipline)

H6 uses the existing multi-asset pipeline, because on majors the flat cost
model is roughly right (mega-tier round trips measured at 1.4–1.9 bps plus
fees). Its declaration is committed unsealed in
`configs/research/crypto_majors_trend_preregistration.yaml`; the seal needs
the dataset bytes, which only your machine can fetch.

```bash
quant-trade data fetch --config configs/data/crypto_majors_kraken_daily.yaml
quant-trade crypto-lowcap seal-majors \
  --data-path data/cache/ccxt-kraken/<the file the fetch printed>.csv \
  --experiment-dir data/experiments/crypto_majors_trend_2026_09
# then edit data_path in the two research configs to the same file and run:
quant-trade research run --config configs/research/crypto_majors_tsmom_preregistered.yaml
quant-trade research walk-forward-multi --config configs/research/walk_forward_crypto_majors_tsmom_preregistered.yaml
quant-trade selection run --outputs outputs --criteria configs/selection/crypto_majors_preregistered.yaml
```

`seal-majors` seals the declaration and a 70/30 holdout against the CSV's
sha256, in that order, and refuses an existing target. The research config's
`split.train_fraction: 0.7` is the same cut. The four declared variants are the
walk-forward grid; the gate's `max_turnover` is derived from the 200 bps/year
drag budget in its header rather than copied from the ETF study.

## 7. Other programmes that are built and blocked only by egress

- **Cash-and-carry H1–H3 (V8/V9):** fully implemented and pre-registered
  (`artifacts/v8/V8_PREREGISTRATION.json`). The acquisition runbook and the
  byte-verified import path are in
  `artifacts/v9/DATA_AND_COST_EVIDENCE_INDEX.json`; your own fee schedule goes
  in through `quant-trade v9 cost-import`. Break-even to clear at 1x costs:
  average settled funding above 11.8% annualised.
- **Capital floor:** `artifacts/v9/SMALL_CAPITAL_FEASIBILITY.json` puts the
  executable floor at $75 and shows the per-fill fee floor eating 52% at the
  bottom rung. Size accordingly before any paper session.

## 8. From a verdict to money: the policy

1. `REVEALED`, `RANGE_ABOVE_ZERO` at recovery 0.0 and the primary gate passing
   at both recoveries → a paper trial with the frozen candidate. The V9
   canary gate (72 h, 500 events) was written for 8-hour funding; a
   low-frequency gate (N rebalances, fills reconciled against the measured
   cost model) is the declared follow-up and does not exist yet.
2. `RANGE_INCLUDES_ZERO` → inconclusive. The only honest cure is more time.
   Nothing is re-tuned.
3. `RANGE_BELOW_ZERO`, or no candidate → the programme closes with its results
   document, as the ETF programme did.
4. Real money is never a code path. It is a human decision taken with a
   reconciled paper record in hand, starting at the executable minimum.
