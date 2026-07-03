from quant_trade.execution.broker import BrokerAccount, BrokerPosition
from quant_trade.execution.reconciliation import reconcile_paper_state_with_broker
from quant_trade.paper.models import PaperPosition, PaperSessionState


def test_reconciliation_matching_and_mismatches() -> None:
    state = PaperSessionState(
        cash=100, equity=200, positions={"SPY": PaperPosition("SPY", 1, last_price=100)}
    )
    account = BrokerAccount("b", "a****", "USD", 100, 100, 200, "active", True)
    ok = reconcile_paper_state_with_broker(state, account, [BrokerPosition("SPY", 1, 100, 90, 10)])
    assert ok.passed
    bad = reconcile_paper_state_with_broker(state, account, [BrokerPosition("QQQ", 2, 200, 90, 10)])
    assert "SPY" in bad.missing_positions
    assert "QQQ" in bad.extra_positions
