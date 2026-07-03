import pandas as pd

from quant_trade.datalake.contracts import validate_contract
from quant_trade.datalake.models import DatasetContract


def test_contract_catches_missing_columns() -> None:
    result = validate_contract("d1", pd.DataFrame({"timestamp": ["2020-01-01"]}), DatasetContract())
    assert result.status == "fail"
    assert "missing required columns" in result.errors[0]
