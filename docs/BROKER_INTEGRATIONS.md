# Broker Integrations

Phase 6 implements Alpaca Paper first because it has a small HTTPS paper API and can be hard-blocked to `https://paper-api.alpaca.markets`. Live trading is not implemented. Paper fills differ from real markets and are not evidence of real-money performance.

IBKR is deferred because it requires TWS/IB Gateway setup, operational supervision, and separate paper validation. The repository contains only a non-network IBKR stub in this phase.

Before any real-money consideration: independent risk review, endpoint redesign, kill switch testing, cloud monitoring, approval workflow, and explicit human authorization are required.
