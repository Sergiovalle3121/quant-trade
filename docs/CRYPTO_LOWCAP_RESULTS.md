# Low/mid-cap crypto campaign: results

**Programme state: `NOT_RUN`.** Research-only. No orders, no funds, no keys.

This document is rendered from the JSON artifacts in the experiment directory by `quant-trade crypto-lowcap report`. Every number carries the evidence class its artifact declared: MEASURED (computed from bytes on disk), ASSUMPTION (a declared choice), NOT_MEASURED (absent, never approximated). Nothing here is a claim about realised money.

## 1. Seal and dataset

- seal id `crypto_lowcap_2026_08`, seal `6740d82b32da0e04…` (MEASURED)
- panel digest `e25722f13e730ddd…`
- selection window 2017-08-17 → 2023-11-28
- holdout window 2023-11-29 → 2026-08-09, reveals used: 0
- panel verification: NOT_RUN (`verify-panel` has not been run here)

## 2. Declared programme

NOT_RUN: no campaign lock; `select` has not been run.

## 3. Selection window (MEASURED, in-sample by construction)

NOT_RUN: `select` has not been run.

## 4. Frozen selection

NOT_RUN: nothing frozen.

## 5. Holdout verdict

NOT_RUN: the holdout is sealed and has not been revealed.

## 6. What is NOT measured

- historical spread and depth: the cost model is one live cross-section (2026-08-05); that it resembles 2018 is an ASSUMPTION
- what a delisted position is worth: reported at recovery 1.0 and 0.0 because neither is the truth
- venue fees: ASSUMPTION-class retail defaults; the fee pages are bot-walled
- anything about the holdout, until the single reveal; and after it, anything beyond one draw over one window the seal declares flatters long-only strategies
- realised money: none was placed; the profit-claim guard refuses the vocabulary

## 7. Reproduction

```bash
quant-trade crypto-lowcap verify-panel --experiment-dir data/experiments/crypto_lowcap_2026_08 --panel data/experiments/crypto_lowcap_2026_08/panel.csv.gz --explain
quant-trade crypto-lowcap select --experiment-dir data/experiments/crypto_lowcap_2026_08 --panel data/experiments/crypto_lowcap_2026_08/panel.csv.gz \
    --trials configs/research/crypto_lowcap_trials.yaml
quant-trade crypto-lowcap reveal --experiment-dir data/experiments/crypto_lowcap_2026_08 --panel data/experiments/crypto_lowcap_2026_08/panel.csv.gz --reason "final evaluation"
quant-trade crypto-lowcap report --experiment-dir data/experiments/crypto_lowcap_2026_08 --output docs/CRYPTO_LOWCAP_RESULTS.md
quant-trade crypto-lowcap horizon --experiment-dir data/experiments/crypto_lowcap_2026_08 --capital 10000 --target 1000000
quant-trade crypto-lowcap doctor --experiment-dir data/experiments/crypto_lowcap_2026_08   # or: make crypto-lowcap-run
```

See `docs/CRYPTO_LOWCAP_RUNBOOK.md` for the dataset re-collection and re-seal paths.

## 8. What this implies for capital

NOT_RUN: `quant-trade crypto-lowcap horizon` has not been run.
