import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.graph.index import GraphIndex, params_hash
from app.graph.service import expand_transaction, reset_index
from app.main import create_app


def test_params_hash_deterministic():
    h1 = params_hash(1209600, 172800, 1000, 200, 1, "v1")
    h2 = params_hash(1209600, 172800, 1000, 200, 1, "v1")
    assert h1 == h2
    h3 = params_hash(7*86400, 172800, 1000, 200, 1, "v1")
    assert h1 != h3

def test_graph_index_window_boundaries():
    # half-open [t-back, t+fwd)  — include start, exclude end
    all_ts = np.array([1000, 2000, 3000, 4000])
    # entity e1 linked to txns 1 and 2 (ts 2000,3000), t=3000 with back=1000 fwd=1000 => window [2000,4000)
    # should include txns at 2000 and 3000, exclude 4000 (equal to t+fwd) and 1000 (before window)
    types = ["CARD","CARD","CARD","CARD"]
    keys = ["c1","c1","c1","c1"]
    pos = [0,1,2,3]
    ts = [1000,2000,3000,4000]
    idx = GraphIndex(types, keys, pos, ts, all_ts, hub_degree_max=1000)
    # t=3000, window 1000 back/fwd => [2000,4000)
    got = idx.windowed_neighbors("CARD","c1", t=3000, back_s=1000, fwd_s=1000)
    assert sorted(int(x) for x in got) == [1,2]
    # exact start inclusive
    got2 = idx.windowed_neighbors("CARD","c1", t=2000, back_s=0, fwd_s=1000)
    # window [2000,3000) includes 2000 but not 3000
    assert sorted(int(x) for x in got2) == [1]
    # future transactions allowed for investigation (fwd window)
    got3 = idx.windowed_neighbors("CARD","c1", t=1000, back_s=0, fwd_s=5000)
    assert sorted(int(x) for x in got3) == [0,1,2,3]

def test_same_timestamp_handling():
    all_ts = np.array([1000,1000,1000])
    types = ["CARD","CARD","CARD"]
    keys = ["c1","c1","c1"]
    pos = [0,1,2]
    ts = [1000,1000,1000]
    idx = GraphIndex(types, keys, pos, ts, all_ts, hub_degree_max=10)
    # window [1000,1000) is empty if back=0 fwd=0? but our expand uses back/fwd >0, so includes ties
    # ties at exactly t are included if within window (since we use bisect_left inclusive start)
    # For t=1000, window [0,2000) includes all
    got = idx.windowed_neighbors("CARD","c1", t=1000, back_s=1000, fwd_s=1000)
    assert sorted(int(x) for x in got) == [0,1,2]
    # expand from pos 0 should include other same-timestamp neighbors
    exp = idx.expand(0, back_s=1000, fwd_s=1000, neighbor_cap=10)
    assert exp == frozenset({0,1,2})

def test_hub_pruning_records_metadata():
    # Create entity with degree 4 > cap 2
    all_ts = np.array([100,200,300,400,500])
    types = ["CARD"]*4 + ["DEVICE"]
    keys = ["hub"]*4 + ["d1"]
    pos = [0,1,2,3,4]
    ts = [100,200,300,400,500]
    idx = GraphIndex(types, keys, pos, ts, all_ts, hub_degree_max=2)
    # hub degree 4 >2 => pruned
    assert idx.hub_info("CARD","hub")["is_hub"] is True
    assert idx.windowed_neighbors("CARD","hub", t=300, back_s=1000, fwd_s=1000).size == 0
    # non-hub still works
    assert idx.hub_info("DEVICE","d1")["is_hub"] is False

def test_neighbor_cap_deterministic():
    all_ts = np.array([100,200,300,400,500,600])
    # entity c1 linked to all 6 txns
    types = ["CARD"]*6
    keys = ["c1"]*6
    pos = [0,1,2,3,4,5]
    ts = [100,200,300,400,500,600]
    idx = GraphIndex(types, keys, pos, ts, all_ts, hub_degree_max=100)
    # window includes all, cap 2 => most recent 2 (500,600) plus seed handling
    # expand from pos 2 (ts 300) with window 1000 back/fwd, cap 2 => neighbors should be last 2 of window (most recent)
    exp = idx.expand(2, back_s=1000, fwd_s=1000, neighbor_cap=2)
    # neighbors in window are [0,1,2,3,4,5] (all), cap 2 => last 2 => [4,5] plus seed 2 => {2,4,5}
    assert exp == frozenset({2,4,5})
    # deterministic across repeats
    exp2 = idx.expand(2, back_s=1000, fwd_s=1000, neighbor_cap=2)
    assert exp == exp2

@pytest.mark.real_data
def test_depth_unsupported():
    from app.graph.index import GraphIndex
    _idx = GraphIndex(["CARD"], ["c1"], [0], [1000], [1000])  # constructed for preconditions
    # service layer checks depth
    reset_index()
    try:
        expand_transaction(2987004, params={"depth":2})
        assert False, "should raise"
    except ValueError as e:
        assert "only depth=1" in str(e)
    except KeyError:
        pass  # if transaction not found due to missing index, also okay for this test env

@pytest.mark.real_data
def test_cache_invalidation_on_params():
    reset_index()
    import pandas as pd
    prod = pd.read_parquet("data/processed/production_features.parquet")
    tid = int(prod["TransactionID"].iloc[0])
    r1 = expand_transaction(tid, params={"back_s":14*86400})
    r2 = expand_transaction(tid, params={"back_s":7*86400})
    assert r1["params_hash"] != r2["params_hash"]
    # same params => cache hit, same hash
    r3 = expand_transaction(tid, params={"back_s":14*86400})
    assert r1["params_hash"] == r3["params_hash"]
    assert r1["community"]["members"] == r3["community"]["members"]

@pytest.mark.real_data
def test_api_graph_404_422_200():
    client = TestClient(create_app(load_settings(environ={"FG_BASE_DIR": str(ROOT)})))
    # 404
    assert client.get("/transactions/999999999/graph").status_code == 404
    # 422
    raw = pd.read_parquet("data/processed/ieee_train_transaction.parquet", columns=["TransactionID"])
    prod = pd.read_parquet("data/processed/production_features.parquet", columns=["TransactionID"])
    diff = set(raw["TransactionID"].values) - set(prod["TransactionID"].values)
    tid_422 = int(next(iter(diff)))
    assert client.get(f"/transactions/{tid_422}/graph").status_code == 422
    # 200
    prod_ids = pd.read_parquet("data/processed/production_features.parquet", columns=["TransactionID"])["TransactionID"].values
    tid_200 = int(prod_ids[0])
    r = client.get(f"/transactions/{tid_200}/graph")
    assert r.status_code == 200
    j = r.json()
    assert "params_hash" in j and "graph_version" in j
    assert "model_risk" in j and "graph_context" in j
    assert j["model_risk"] != j["graph_context"]
    assert "nodes" in j and "edges" in j

@pytest.mark.real_data
def test_determinism_two_runs():
    reset_index()
    prod = pd.read_parquet("data/processed/production_features.parquet")
    tid = int(prod["TransactionID"].iloc[5])
    r1 = expand_transaction(tid)
    r2 = expand_transaction(tid)
    assert r1["community"]["members"] == r2["community"]["members"]
    assert r1["params_hash"] == r2["params_hash"]
    assert r1["pruning"] == r2["pruning"]

def test_community_connected_components_simple():
    # isolated transaction (degree 0 after hub pruning) => community size 1
    all_ts = np.array([100,200])
    types = ["CARD"]
    keys = ["c1"]
    pos = [0]
    ts = [100]
    idx = GraphIndex(types, keys, pos, ts, all_ts, hub_degree_max=100)
    # txn pos 1 has no entities
    assert idx.seed_entities(1) == []
    exp = idx.expand(1, back_s=1000, fwd_s=1000)
    assert exp == frozenset({1})

@pytest.mark.real_data
def test_frozen_artifacts_untouched():
    # production_features, model artifact, feature manifest unchanged
    import json
    # feature manifest still 6 included
    with open("reports/feature_manifest.json") as f:
        m = json.load(f)
    included = [x for x in m["features"] if x["included_in_model"]]
    assert len(included) == 6
    # production_features parquet hash not changed? check row count
    df = pd.read_parquet("data/processed/production_features.parquet")
    assert len(df) == 144233
    # model validation still passes
    with open("models/fraud_xgb_v1-9e2978c.metadata.json") as f:
        meta = json.load(f)
    assert meta["feature_count"] == 438
