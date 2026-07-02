# Risk Policy

- The platform does not support live trading yet.
- No leverage, shorting, margin, or derivatives are supported in the initial simulator.
- Position and trade size caps are mandatory for backtests.
- Future live systems need explicit max drawdown limits, exposure limits, order throttles, and a kill switch.
- Paper trading must demonstrate stable operations, reconciliation, monitoring, and risk controls before real capital.
- Backtests can lie because of lookahead bias, overfitting, survivorship bias, poor cost assumptions, and market regime changes.
- Future validation must include walk-forward analysis and out-of-sample testing.
