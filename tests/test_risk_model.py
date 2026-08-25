import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]

import numpy as np
import pandas as pd
import pytest
from xgboost import XGBClassifier

from app.risk.explain import top_k_contributions
from app.risk.registry import RegistryError, load_model
from app.risk.scorer import RiskScorer


def test_model_artifact_exists():
    from app.config import get_settings
    s = get_settings()
    assert (s.model_dir / "latest.json").exists()
    assert (s.model_dir / "latest.metadata.json").exists()

def test_load_and_feature_order():
    _clf, meta, feats = load_model("latest")
    assert len(feats) == 438 == meta["feature_count"]
    assert feats[-6:] == ["amt_z_card","amt_z_device","hour_dev_card","hour_dev_device","hours_since_last_card","hours_since_last_device"]
    assert "tx_prior" not in ",".join(feats)

def test_registry_fails_on_missing(tmp_path):
    from app.config import load_settings
    s = load_settings(environ={"FG_BASE_DIR": str(tmp_path), "FG_DB_PATH": str(tmp_path/"x.duckdb")})
    with pytest.raises(RegistryError):
        load_model("latest", model_dir=s.model_dir)

def test_metadata_validation_banned():
    _clf, _meta, feats = load_model("latest")
    # ensure no banned markers
    for n in feats:
        assert "tx_prior" not in n

def test_score_range_and_determinism():
    scorer = RiskScorer()
    # build tiny fixture
    X = np.random.randn(10, 438).astype("float32")
    X = np.nan_to_num(X, nan=0.0)
    s1 = scorer.score_matrix(X)
    s2 = scorer.score_matrix(X)
    assert np.allclose(s1, s2)
    assert ((s1 >= 0) & (s1 <= 1)).all()

def test_feature_count_mismatch():
    from app.risk.registry import validate_feature_matrix
    _clf, _meta, feats = load_model("latest")
    with pytest.raises(RegistryError):
        validate_feature_matrix(np.zeros((1, 10)), feats)

def test_explanation_structure():
    clf, _meta, feats = load_model("latest")
    X_row = np.random.randn(438).astype("float32")
    contribs = top_k_contributions(clf, X_row, feats, k=3)
    assert len(contribs) == 3
    for c in contribs:
        assert "feature" in c and "contribution" in c and "direction" in c

def test_tiny_model_fixture(tmp_path):
    # Train tiny model on 20 rows to test serialization without full data
    X = np.random.randn(20, 5).astype("float32")
    y = np.array([0,1]*10)
    clf = XGBClassifier(n_estimators=10, max_depth=2, tree_method="hist", random_state=0, eval_metric="logloss")
    clf.fit(X, y)
    p = tmp_path / "tiny.json"
    clf.save_model(str(p))
    clf2 = XGBClassifier()
    clf2.load_model(str(p))
    assert np.allclose(clf.predict_proba(X)[:,1], clf2.predict_proba(X)[:,1])

@pytest.mark.real_data
def test_integration_production_model_scores_known_transaction():
    from fastapi.testclient import TestClient

    from app.config import load_settings
    from app.main import create_app
    prod = pd.read_parquet("data/processed/production_features.parquet")
    tid = int(prod["TransactionID"].iloc[0])
    s = load_settings(environ={"FG_BASE_DIR": str(ROOT)})
    client = TestClient(create_app(s))
    r = client.get(f"/transactions/{tid}/risk")
    assert r.status_code == 200
    j = r.json()
    assert 0 <= j["risk_score"] <= 1
    assert j["model_version"] == "fraud_xgb_v1-9e2978c"
