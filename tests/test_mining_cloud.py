Exit code: 0
Wall time: 0.8 seconds
Output:
import pytest

from quant_trade.mining.cloud import publish_report


class FakeStorage:
    def __init__(self):
        self.uri = None
        self.data = None

    def write_json(self, uri, data):
        self.uri = uri
        self.data = data


def test_report_publisher_uses_injected_storage_without_network():
    storage = FakeStorage()
    publish_report({"decision": "NO-GO"}, "s3://bucket/mining/report.json", storage)
    assert storage.uri == "s3://bucket/mining/report.json"
    assert storage.data == {"decision": "NO-GO"}


def test_report_publisher_rejects_non_s3_uri():
    with pytest.raises(ValueError, match="s3://"):
        publish_report({}, "https://example.com/report.json", FakeStorage())

