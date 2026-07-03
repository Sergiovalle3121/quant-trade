from quant_trade.evidence.database import TABLES, connect, initialize_database


def test_evidence_database_initializes(tmp_path):
    db = tmp_path / "evidence.sqlite"
    initialize_database(db)
    with connect(db) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert set(TABLES).issubset(names)
