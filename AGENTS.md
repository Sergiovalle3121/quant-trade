# AI Agent Instructions

- Keep changes small, deterministic, and testable.
- Never commit secrets, API keys, tokens, credentials, or private data.
- Never add real-money trading, broker connectivity, paid data integrations, order routing, or execution without explicit human approval.
- Always add or update tests for strategy, backtest, metrics, and risk-management changes.
- Prefer simple, readable code over clever code.
- Use Python type hints and clear domain names.
- Explain assumptions, limitations, and model risk in documentation.
- Do not optimize for fake backtest profits or hide unfavorable results.
- This repository is research/backtesting only until explicitly approved otherwise.


## Data provider rules

- Never commit market data cache files.
- Never commit API keys, secrets, or `.env` files.
- Data provider tests must be mocked and must not require network access.
- Any new provider must normalize to the canonical OHLCV schema and include validation tests.
- No live trading, broker execution APIs, order routing, or real-money trading.

## Phase 4 research lab guidance

Multi-asset strategy lab code remains research/backtesting only. Do not add broker connectivity, order routing, live trading, secrets, or real-money execution. Keep benchmark, robustness, and cost assumptions explicit.

## Phase 5 safety

Paper trading code must remain simulated-only using local/cached data. Do not add live broker adapters, secrets, real order routing, or real-money trading paths.

## Phase 6 broker integration safety

Alpaca support is paper-only. Keep live endpoints, live keys, shorting, leverage, and real-money execution out of the repository. Broker tests must mock network calls.

## Phase 7 cloud safety

Cloud deployment code is paper-only. Defaults must remain dry-run, AWS credentials must be optional, Terraform apply must be manual, and live broker endpoints remain prohibited.


## Phase 8 operations safety

- Operations code must never call broker/network in tests.
- Never expose secrets in dashboard/alerts/incidents.
- New alert categories need tests.
- New readiness criteria need docs.
- Retention deletes require explicit confirmation.
- No command may imply real-money readiness.

## Phase 9 trial-management safety

- Trial code must never approve real-money trading.
- Review packs must always include a paper-only warning.
- Decision records must always set `real_money_approved=false`.
- Missing evidence should fail conservative checks.
- New decision statuses require tests and docs.
- No secrets in trial artifacts.


## Phase 15 data lake safety

Data lake code is research/backtesting only. Do not commit generated datasets, snapshots, manifests, market data, secrets, or paid-provider responses. Data lake tests must remain offline and deterministic. Dataset versions and quality reports do not imply live-trading readiness.

## Session C crypto campaign safety

- The trial grid (`configs/research/crypto_lowcap_trials.yaml`) and every gate file are locked on first `select`; never edit them after a run, register a new experiment instead.
- Never read a holdout date outside `reveal`; never call `reveal` twice; never edit a sealed pre-registration, holdout seal or frozen selection.
- The results document is rendered from artifacts only and must keep passing the profit-claim guard.
- Panels, journals and caches stay git-ignored; digests, seals, ledgers, verifications and verdicts are committed.

## Phase 16 backtest audit safety

- The audit (`src/quant_trade/audit/`) analyses files a client uploads. It never executes, recommends, custodies or connects to a broker or exchange, and never claims that money was or will be made.
- Every verdict sentence, page and report must pass the profit-claim guard in English and Spanish (`audit/guard.py`); a sentence that fails it is a bug, not a report.
- Every reported number carries an evidence tag (`MEASURED`, `DECLARED`, `NOT_MEASURED`). Do not report a client declaration as measured.
- Uploads, the audit database and generated reports stay git-ignored (`state/`, `outputs/`). Never commit a client file.
- No secret has a default. Stripe keys and `DATABASE_URL` come from the environment only; free mode is forced when any Stripe variable is missing, unless the owner explicitly opts into selling access codes (`AUDIT_ACCESS_CODES=true` with `AUDIT_FREE_MODE=false`).
- Web tests use `TestClient` with Stripe simulated by the HMAC helper; nothing reaches the network in tests.
- A new red flag, threshold or dimension needs a test and a line in `docs/AUDIT_SAAS.md`.
- Retention deletes require explicit confirmation (`audit purge --yes`).
- Badge, verification page and challenge texts never imply future results. The badge shows class, id, date and the fixed notice only; never growth, return or profit.
- The public verification page is built from an allow-list: it never shows files, trades, the description or the token.
- Prop-firm presets carry their source URL and `as_of` date.
- Access codes are stored only as a hash and printed once; nothing lists or logs a clear code.
- The terms and privacy pages (`audit/legal.py`) must pass the guard; operator details come from the environment with no real-looking default. Every privacy promise needs a command that keeps it and a test.
