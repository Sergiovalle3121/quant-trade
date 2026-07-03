import pandas as pd

from quant_trade.tca.spread import estimate_bid_ask_spread_proxy
from quant_trade.tca.volume import estimate_volume_capacity


def test_spread_and_capacity_proxies():
    df = pd.DataFrame({"high":[101],"low":[99],"close":[100],"volume":[1000]})
    assert estimate_bid_ask_spread_proxy(df).iloc[0] >= 1
    assert estimate_volume_capacity(df, 0.1).iloc[0] == 100
