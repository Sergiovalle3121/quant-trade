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

## Phase 17 human approval safety

Approval workflow code must remain local and paper-only. `real_money_approved` must always be false, approval tests must be offline, and broker/cloud approval gates must not call live endpoints or store secrets.
