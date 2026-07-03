# Secrets Management

Never commit `.env`, API keys, tokens, credentials, account exports, or private broker data. Phase 6 uses paper-specific variables only: `ALPACA_PAPER_API_KEY`, `ALPACA_PAPER_SECRET_KEY`, and `ALPACA_PAPER_BASE_URL=https://paper-api.alpaca.markets`.

Do not use live Alpaca keys or generic `ALPACA_API_KEY` names. Set local environment variables in your shell or an untracked `.env`. CI must not print secrets and does not need broker credentials.

For future cloud deployment, store secrets in GitHub Actions secrets or AWS Secrets Manager, inject them at runtime, redact logs, rotate keys periodically, and revoke/regenerate immediately if a key leaks. Use secret scanning and review audit logs for accidental exposure.

## Phase 7 cloud paper deployment note

Scheduled cloud workflows are paper-only and fail closed. Defaults are dry-run; paper submission requires explicit config, official Alpaca Paper endpoint credentials from env or AWS Secrets Manager, kill switch clear, and reviewed operations. No live trading endpoints or real-money execution are supported.
