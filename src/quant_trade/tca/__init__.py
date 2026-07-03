"""Execution Quality Lab + Transaction Cost Analysis v2 (offline, paper-only)."""
from quant_trade.tca.analysis import compare_research_vs_paper_execution, generate_tca_report
from quant_trade.tca.partial_fills import simulate_partial_fills
from quant_trade.tca.slippage import calculate_implementation_shortfall, calculate_slippage_bps
from quant_trade.tca.spread import estimate_bid_ask_spread_proxy
from quant_trade.tca.volume import estimate_volume_capacity

__all__ = [
    "calculate_implementation_shortfall",
    "calculate_slippage_bps",
    "compare_research_vs_paper_execution",
    "estimate_bid_ask_spread_proxy",
    "estimate_volume_capacity",
    "generate_tca_report",
    "simulate_partial_fills",
]
