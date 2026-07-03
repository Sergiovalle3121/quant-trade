import sys

import pytest

from quant_trade.cloud.exceptions import StorageError
from quant_trade.cloud.storage import LocalStorageBackend, S3StorageBackend, parse_s3_uri


def test_local_storage_json(tmp_path):
    st = LocalStorageBackend()
    p = tmp_path / "a" / "b.json"
    st.write_json(str(p), {"x": 1})
    assert st.read_json(str(p)) == {"x": 1}
    assert st.exists(str(p))


def test_s3_parse():
    assert parse_s3_uri("s3://bucket/a/b.json") == ("bucket", "a/b.json")


def test_s3_mocked_read_write():
    class Body:
        def read(self):
            return b'{"ok": true}'

    class C:
        def __init__(self):
            self.put = None

        def put_object(self, **kw):
            self.put = kw

        def get_object(self, **kw):
            return {"Body": Body()}

    c = C()
    st = S3StorageBackend(c)
    st.write_json("s3://b/k.json", {"x": 2})
    assert c.put["Bucket"] == "b"
    assert st.read_json("s3://b/k.json")["ok"] is True


def test_s3_missing_boto3(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)
    st = S3StorageBackend()
    with pytest.raises(StorageError, match="pip install"):
        _ = st.client
