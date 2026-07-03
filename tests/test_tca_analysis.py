from quant_trade.tca.analysis import compare_research_vs_paper_execution, summarize
from quant_trade.tca.models import OrderExecutionAnalysis


def test_higher_costs_reduce_quality_and_empty_fills_handled():
    assert summarize([], 100000).order_count == 0
    row = OrderExecutionAnalysis("1","SPY","buy",10,10,100,100,102,20,200,5,0,0,20,"filled",1,190)
    comparison = compare_research_vs_paper_execution([row], research_assumed_cost_bps=10)
    assert comparison["quality_reduced_by_costs"] is True
    assert comparison["real_money_ready"] is False
