# Minimal transaction queue API
# Read-only ranking over existing risk_predictions + evidence tables.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MODEL_VERSION = "fraud_xgb_v1-9e2978c"


def _seed(conn):
    rows = [
        (101, 0.97, "CRITICAL", 1),
        (102, 0.88, "HIGH", 1),
        (103, 0.65, "MEDIUM", 0),
        (104, 0.10, "LOW", 0),
    ]
    for tid, score, band, has_ev in rows:
        conn.execute(
            "INSERT OR REPLACE INTO risk_predictions VALUES"
            " (?, ?, ?, ?, NULL)", [tid, MODEL_VERSION, score, band])
        if has_ev:
            conn.execute(
                "INSERT OR REPLACE INTO evidence VALUES"
                " (?, ?, 'NEW_PAIRING', '{}', 'h', NULL)",
                [f"ev-{tid}", tid])


def test_queue_ranks_by_score_desc(client):
    from app.storage.db import connect
    conn = connect(client.app.state.settings.db_path)
    _seed(conn)
    conn.close()
    r = client.get("/transactions")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 4
    scores = [t["risk_score"] for t in body["transactions"]]
    assert scores == sorted(scores, reverse=True)
    top = body["transactions"][0]
    assert top["transaction_id"] == 101
    assert top["risk_band"] == "CRITICAL"
    assert top["model_version"] == MODEL_VERSION
    assert top["has_evidence"] is True


def test_queue_filters(client):
    from app.storage.db import connect
    conn = connect(client.app.state.settings.db_path)
    _seed(conn)
    conn.close()
    r = client.get("/transactions", params={"band": "HIGH"})
    assert [t["transaction_id"] for t in r.json()["transactions"]] == [102]
    r = client.get("/transactions", params={"min_score": 0.8})
    assert {t["transaction_id"] for t in r.json()["transactions"]} == {101, 102}
    r = client.get("/transactions", params={"has_evidence": True})
    assert {t["transaction_id"] for t in r.json()["transactions"]} == {101, 102}
    r = client.get("/transactions", params={"limit": 2})
    assert r.json()["count"] == 2


def test_queue_bad_band_422_and_uninitialized_503(tmp_path):
    from fastapi.testclient import TestClient

    from app.config import load_settings
    from app.main import create_app
    s = load_settings(environ={"FG_BASE_DIR": str(tmp_path),
                               "FG_DB_PATH": str(tmp_path / "q.duckdb")})
    c = TestClient(create_app(s))
    assert c.get("/transactions").status_code == 503


def test_queue_bad_band_422(client):
    r = client.get("/transactions", params={"band": "EXTREME"})
    assert r.status_code == 422
