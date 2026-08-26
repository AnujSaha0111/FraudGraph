import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app


def _client():
    return TestClient(create_app(load_settings(environ={"FG_BASE_DIR": str(ROOT)})))

@pytest.mark.real_data
def test_risk_200():
    prod = pd.read_parquet("data/processed/production_features.parquet")
    tid = int(prod["TransactionID"].iloc[10])
    r = _client().get(f"/transactions/{tid}/risk")
    assert r.status_code == 200
    j = r.json()
    assert "risk_score" in j and "risk_band" in j

@pytest.mark.real_data
def test_risk_404():
    assert _client().get("/transactions/999999999/risk").status_code == 404

@pytest.mark.real_data
def test_risk_422():
    raw = pd.read_parquet("data/processed/ieee_train_transaction.parquet", columns=["TransactionID"])
    prod = pd.read_parquet("data/processed/production_features.parquet", columns=["TransactionID"])
    diff = set(raw["TransactionID"].values) - set(prod["TransactionID"].values)
    tid = int(next(iter(diff)))
    r = _client().get(f"/transactions/{tid}/risk")
    assert r.status_code == 422

@pytest.mark.real_data
def test_risk_503(tmp_path):
    s = load_settings(environ={"FG_BASE_DIR": str(tmp_path), "FG_DB_PATH": str(tmp_path/"x.duckdb")})
    c = TestClient(create_app(s))
    prod = pd.read_parquet("data/processed/production_features.parquet")
    tid = int(prod["TransactionID"].iloc[0])
    assert c.get(f"/transactions/{tid}/risk").status_code == 503

@pytest.mark.real_data
def test_explanation_200():
    prod = pd.read_parquet("data/processed/production_features.parquet")
    tid = int(prod["TransactionID"].iloc[0])
    r = _client().get(f"/transactions/{tid}/risk/explanation?k=5")
    assert r.status_code == 200
    j = r.json()
    assert len(j["top_features"]) == 5
    assert all("contribution" in f for f in j["top_features"])

@pytest.mark.real_data
def test_explanation_404_422():
    assert _client().get("/transactions/999999999/risk/explanation").status_code == 404
    raw = pd.read_parquet("data/processed/ieee_train_transaction.parquet", columns=["TransactionID"])
    prod = pd.read_parquet("data/processed/production_features.parquet", columns=["TransactionID"])
    diff = set(raw["TransactionID"].values) - set(prod["TransactionID"].values)
    tid = int(next(iter(diff)))
    assert _client().get(f"/transactions/{tid}/risk/explanation").status_code == 422

@pytest.mark.real_data
def test_score_persistence():
    from app.config import get_settings
    from app.storage.db import connect
    s = get_settings()
    conn = connect(s.db_path)
    cnt = conn.execute("SELECT COUNT(*) FROM risk_predictions").fetchone()[0]
    assert cnt == 144233
    conn.close()
