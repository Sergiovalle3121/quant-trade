"""Slippage and shortfall calculations."""


def calculate_slippage_bps(
    arrival_price: float, execution_price: float, side: str = "buy"
) -> float:
    if arrival_price <= 0:
        return 0.0
    if side.lower() == "buy":
        signed = execution_price - arrival_price
    else:
        signed = arrival_price - execution_price
    return signed / arrival_price * 10000.0


def calculate_implementation_shortfall(
    decision_price: float,
    execution_price: float,
    quantity: float,
    side: str = "buy",
) -> float:
    if side.lower() == "buy":
        signed = execution_price - decision_price
    else:
        signed = decision_price - execution_price
    return signed * abs(quantity)
