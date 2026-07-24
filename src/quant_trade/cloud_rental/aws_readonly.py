"""Read-only AWS price adapters. NO create/run/terminate verbs exist here.

Two separate price families that are never mixed:
- On-demand: the AWS Price List Query API (``pricing`` service).
- Spot: EC2 ``DescribeSpotPriceHistory``.

Uses ordinary ambient credentials when present (never printed, never written),
lazy-imports boto3, and returns :class:`ComputeQuote` records stamped with the
source kind so downstream validation can prove the family separation. This
module is not exercised by tests (no credentials, no network there); offline
fixtures stand in.
"""

from __future__ import annotations

import json
import time
from typing import Any

from quant_trade.cloud_rental.models import CloudProvider, ComputeQuote, PurchaseModel


def _now_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class AwsReadOnlyPriceAdapter:
    """Price reads only. There is deliberately no RunInstances anywhere."""

    def __init__(self, region: str = "us-east-1", timeout_seconds: float = 15.0) -> None:
        self.region = region
        self.timeout_seconds = timeout_seconds

    def _pricing_client(self) -> Any:
        import boto3  # lazy: requires the `cloud` extra + ambient credentials
        from botocore.config import Config

        return boto3.client(
            "pricing",
            region_name="us-east-1",  # the Pricing API lives in us-east-1
            config=Config(connect_timeout=self.timeout_seconds, retries={"max_attempts": 2}),
        )

    def _ec2_client(self) -> Any:
        import boto3
        from botocore.config import Config

        return boto3.client(
            "ec2",
            region_name=self.region,
            config=Config(connect_timeout=self.timeout_seconds, retries={"max_attempts": 2}),
        )

    def fetch_on_demand_quote(
        self, instance_type: str, *, operating_system: str = "Linux"
    ) -> ComputeQuote:
        """On-demand price from the Price List Query API (never Spot)."""
        client = self._pricing_client()
        response = client.get_products(
            ServiceCode="AmazonEC2",
            Filters=[
                {"Type": "TERM_MATCH", "Field": "instanceType", "Value": instance_type},
                {"Type": "TERM_MATCH", "Field": "regionCode", "Value": self.region},
                {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": operating_system},
                {"Type": "TERM_MATCH", "Field": "tenancy", "Value": "Shared"},
                {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": "NA"},
                {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"},
            ],
            MaxResults=1,
        )
        if not response.get("PriceList"):
            raise ValueError(f"no Price List entry for {instance_type} in {self.region}")
        product = json.loads(response["PriceList"][0])
        on_demand = next(iter(product["terms"]["OnDemand"].values()))
        dimension = next(iter(on_demand["priceDimensions"].values()))
        price = float(dimension["pricePerUnit"]["USD"])
        return ComputeQuote(
            provider=CloudProvider.AWS,
            sku=instance_type,
            region=self.region,
            purchase_model=PurchaseModel.ON_DEMAND,
            price_per_hour=price,
            currency="USD",
            source_kind="price_list",
            source_name="aws_price_list_query",
            captured_at_utc=_now_utc(),
            source_url="https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/price-changes.html",
            operating_system=operating_system,
        )

    def fetch_spot_quote(self, instance_type: str) -> ComputeQuote:
        """Most recent Spot price from DescribeSpotPriceHistory (never Price List)."""
        client = self._ec2_client()
        response = client.describe_spot_price_history(
            InstanceTypes=[instance_type],
            ProductDescriptions=["Linux/UNIX"],
            MaxResults=1,
        )
        history = response.get("SpotPriceHistory") or []
        if not history:
            raise ValueError(f"no Spot price history for {instance_type} in {self.region}")
        latest = history[0]
        return ComputeQuote(
            provider=CloudProvider.AWS,
            sku=instance_type,
            region=self.region,
            zone=str(latest.get("AvailabilityZone", "")),
            purchase_model=PurchaseModel.SPOT,
            price_per_hour=float(latest["SpotPrice"]),
            currency="USD",
            source_kind="spot_price_history",
            source_name="aws_describe_spot_price_history",
            captured_at_utc=_now_utc(),
            source_url="https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeSpotPriceHistory.html",
        )
