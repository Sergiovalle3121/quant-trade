"""Read-only Alibaba Cloud price adapter. NO CreateInstance verbs exist here.

Prices come from ECS ``DescribePrice`` (pay-as-you-go and preemptible via
SpotStrategy). The SDK import is lazy; ambient credentials are used only when
present and never printed. Currency and FX are explicit — Alibaba may quote in
CNY or USD depending on site/account. Not exercised by tests; offline fixtures
stand in.
"""

from __future__ import annotations

import time

from quant_trade.cloud_rental.models import CloudProvider, ComputeQuote, PurchaseModel


def _now_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class AlibabaReadOnlyPriceAdapter:
    """DescribePrice reads only. There is deliberately no CreateInstance."""

    def __init__(self, region: str = "us-west-1", timeout_seconds: float = 15.0) -> None:
        self.region = region
        self.timeout_seconds = timeout_seconds

    def fetch_quote(
        self,
        instance_type: str,
        *,
        preemptible: bool = False,
        fx_rate_to_usd: float = 1.0,
        currency: str = "USD",
    ) -> ComputeQuote:
        """Pay-as-you-go or preemptible hourly price via DescribePrice."""
        # Lazy import: requires the alibabacloud ECS SDK, which is intentionally
        # NOT a project dependency until real quoting is needed.
        from alibabacloud_ecs20140526.client import Client
        from alibabacloud_ecs20140526.models import DescribePriceRequest
        from alibabacloud_tea_openapi.models import Config

        client = Client(
            Config(
                region_id=self.region,
                connect_timeout=int(self.timeout_seconds * 1000),
                endpoint=f"ecs.{self.region}.aliyuncs.com",
            )
        )
        request = DescribePriceRequest(
            region_id=self.region,
            resource_type="instance",
            instance_type=instance_type,
        )
        if preemptible:
            request.spot_strategy = "SpotAsPriceGo"
        response = client.describe_price(request)
        price_info = response.body.price_info.price
        return ComputeQuote(
            provider=CloudProvider.ALIBABA,
            sku=instance_type,
            region=self.region,
            purchase_model=(
                PurchaseModel.PREEMPTIBLE if preemptible else PurchaseModel.ON_DEMAND
            ),
            price_per_hour=float(price_info.trade_price),
            currency=currency,
            fx_rate_to_usd=fx_rate_to_usd,
            source_kind="describe_price",
            source_name="alibaba_ecs_describe_price",
            captured_at_utc=_now_utc(),
            source_url=(
                "https://www.alibabacloud.com/help/en/ecs/developer-reference/"
                "api-ecs-2014-05-26-describeprice"
            ),
        )
