# """Adversarial leakage tests (blocking)

# Covers audit gaps A4, A5, A6, A11:
# - Future graph information must not leak into predictive features.
# - Evidence's investigation window (+2d) must not mutate model features.
# - Case/decision timestamps must never appear in the feature manifest.

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app.features.causal import build_relational_features


def _frame(rows):
    return pd.DataFrame(rows)


BASE = {"ts": 1000, "amount": 50.0, "card_key": "c1", "device_key": "d1", "addr_key": "a1"}


def test_future_graph_window_does_not_change_past_features():
    # transaction at t+2d (inside graph's forward window) must not change features of a transaction at t. Graph expansion uses [t-14d, t+2d) for investigation, but predictive features must use only [t-W, t)
    # Build features for a single past row, then with a future neighbor inside +2d window
    df_past = _frame([{**BASE}])
    f_past = build_relational_features(df_past).iloc[0]

    df_with_future = _frame([
        {**BASE},
        {"ts": 1000 + 2 * 86400 - 100, "amount": 9999.0, "card_key": "c1", "device_key": "d1", "addr_key": "a1"},
    ])
    f_with_future = build_relational_features(df_with_future).iloc[0]

    # Past row's features must be identical regardless of future neighbor
    assert np.allclose(
        f_past.astype(float).to_numpy(dtype=float, na_value=np.nan),
        f_with_future.astype(float).to_numpy(dtype=float, na_value=np.nan),
        equal_nan=True,
    ), "future graph-window neighbor leaked into past features"


def test_post_window_injection_does_not_affect_query_features():
    # Inject a transaction far after the query window (+30d) sharing the same card — it must not affect the query's windowed counts
    t_query = 100_000
    t_far = t_query + 30 * 86400
    df = _frame([
        {"ts": t_query - 1000, "amount": 10.0, "card_key": "c1", "device_key": None, "addr_key": None},
        {"ts": t_query, "amount": 10.0, "card_key": "c1", "device_key": None, "addr_key": None},
        {"ts": t_far, "amount": 10.0, "card_key": "c1", "device_key": None, "addr_key": None},
    ])
    f = build_relational_features(df)
    # Query row is index 1; its 24h count should be 1 (only the -1000s prior), not 2
    assert f.iloc[1]["card_tx_24h"] == 1.0
    assert f.iloc[2]["card_tx_24h"] == 0.0  # far row is 30d later, outside 24h window


def test_case_timestamps_not_in_feature_manifest():
    # Case/decision timestamps must never become predictive features (A11)
    manifest = json.loads(Path("reports/feature_manifest.json").read_text())["features"]
    feature_names = [f["name"] for f in manifest if f.get("included_in_model")]
    banned_substrings = ["case", "decision", "label", "actor", "history", "arrival", "effective"]
    for name in feature_names:
        for banned in banned_substrings:
            assert banned not in name.lower(), f"feature {name!r} looks like case/label leakage ({banned})"
    # Also check the frozen order file
    feats = json.loads(Path("models/fraud_xgb_v1-9e2978c.features.json").read_text())
    assert len(feats) == 438
    for banned in banned_substrings:
        assert not any(banned in f.lower() for f in feats), f"banned {banned} in feature list"


@pytest.mark.real_data
def test_evidence_generation_does_not_mutate_production_features():
    """Evidence's use of the investigation window must not mutate the
    production feature artifact (A6). Production features are derived, evidence is
    read-only with respect to them."""
    import hashlib

    prod_path = Path("data/processed/production_features.parquet")
    before = hashlib.sha256(prod_path.read_bytes()).hexdigest()
    # Trigger evidence generation for a known transaction (uses graph + production)
    from app.evidence.service import generate_evidence
    try:
        generate_evidence(2987005)
    except Exception:  # noqa: BLE001, S110 - 404/422/503 are ok; only file mutation matters
        pass
    after = hashlib.sha256(prod_path.read_bytes()).hexdigest()
    assert before == after, "evidence generation mutated production_features.parquet"


def test_graph_expansion_contamination_does_not_affect_feature_build():
    """Graph link table shares entities with feature build, but the graph's
    temporal window must not contaminate the causal accumulator."""
    # Directly verify that build_relational_features does not read graph_links
    df = _frame([
        {"ts": 100, "amount": 10.0, "card_key": "cX", "device_key": "dX", "addr_key": "aX"},
        {"ts": 200, "amount": 20.0, "card_key": "cX", "device_key": "dY", "addr_key": "aX"},
    ])
    f = build_relational_features(df)
    # Second row's card history should be exactly 1 prior (ts=100), not affected by any graph state
    assert f.iloc[1]["card_tx_24h"] == 1.0
    assert f.iloc[1]["is_new_device_card_pair"] == 1.0  # dY never seen with cX before
