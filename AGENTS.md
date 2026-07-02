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
