# Graph investigation service — clean separation from HTTP
import time
from typing import Any

import numpy as np
import pandas as pd

from app.config import get_settings
from app.graph.index import GRAPH_VERSION, GraphIndex, params_hash

# In-memory singleton index built at startup
_index: GraphIndex | None = None
_index_meta: dict | None = None
_cache: dict[str, Any] = {}

DEFAULT_BACK_S = 14 * 86400
DEFAULT_FWD_S = 2 * 86400
DEFAULT_HUB_MAX = 1000
DEFAULT_NEIGHBOR_CAP = 200
DEFAULT_DEPTH = 1

def get_default_params(settings=None) -> dict:
    s = settings or get_settings()
    return {
        "back_s": s.window_back_days * 86400,
        "fwd_s": s.window_fwd_days * 86400,
        "hub_degree_max": s.hub_degree_max,
        "neighbor_cap": s.neighbor_cap,
        "depth": s.expansion_depth,
        "graph_version": GRAPH_VERSION,
    }

def _load_index(settings=None) -> tuple[GraphIndex, dict]:
    global _index, _index_meta
    if _index is not None:
        return _index, _index_meta
    s = settings or get_settings()
    # Load graph_links parquet or build if missing
    gl_path = s.processed_dir / "graph_links.parquet"
    if not gl_path.exists():
        # build from experiment_base
        from app.graph.build import build_graph_links
        build_graph_links(s.processed_dir / "experiment_base.parquet", gl_path, s.db_path)
    links = pd.read_parquet(gl_path)
    # Need all_ts array ordered by txn position (experiment_base order is original CSV order? We need deterministic txn_pos mapping)
    # We use experiment_base order as position
    df = pd.read_parquet(s.processed_dir / "experiment_base.parquet", columns=["TransactionID", "TransactionDT"])
    df_sorted = df.reset_index(drop=True)
    # Map transaction_id to position (row index in df_sorted)
    pos_of_id = {tid: i for i, tid in enumerate(df_sorted["TransactionID"].values)}
    # all_ts in position order
    all_ts = df_sorted["TransactionDT"].to_numpy(dtype=np.int64)
    # links: entity_type, entity_key, transaction_id, ts
    # map to txn_positions
    txn_positions = [pos_of_id[tid] for tid in links["transaction_id"].values]
    entity_types = links["entity_type"].values
    entity_keys = links["entity_key"].values
    link_ts = links["ts"].values
    t0 = time.perf_counter()
    idx = GraphIndex(entity_types, entity_keys, txn_positions, link_ts, all_ts, hub_degree_max=s.hub_degree_max)
    build_s = time.perf_counter() - t0
    meta = {"n_links": len(links), "n_entities": idx.n_entities, "build_seconds": round(build_s,3), "graph_version": GRAPH_VERSION}
    _index = idx
    _index_meta = meta
    return idx, meta

def reset_index():
    global _index, _index_meta
    _index = None
    _index_meta = None
    _cache.clear()

def expand_transaction(transaction_id: int, params: dict | None = None, settings=None) -> dict:
    s = settings or get_settings()
    idx, _meta = _load_index(s)
    # resolve transaction position
    df = pd.read_parquet(s.processed_dir / "experiment_base.parquet", columns=["TransactionID", "TransactionDT"])
    pos_map = {tid: i for i, tid in enumerate(df["TransactionID"].values)}
    if transaction_id not in pos_map:
        # check raw existence for 404 vs 422
        raw_ids = set(pd.read_parquet(s.processed_dir / "ieee_train_transaction.parquet", columns=["TransactionID"])["TransactionID"].values)
        if transaction_id in raw_ids:
            raise ValueError("422")
        raise KeyError("404")
    pos = pos_map[transaction_id]
    # params
    p = get_default_params(s)
    if params:
        p.update({k: int(v) for k,v in params.items() if k in p})
    if p["depth"] != 1:
        raise ValueError("only depth=1 supported")
    ph = params_hash(p["back_s"], p["fwd_s"], p["hub_degree_max"], p["neighbor_cap"], p["depth"], p["graph_version"])
    cache_key = f"{transaction_id}:{ph}"
    if cache_key in _cache:
        return _cache[cache_key]
    # expand
    detail = idx.expand_detailed(int(pos), p["back_s"], p["fwd_s"], p["neighbor_cap"], p["depth"])
    # Map positions back to transaction_ids and timestamps
    chosen = detail["chosen_positions"]
    chosen_ids = [int(df["TransactionID"].iloc[c]) for c in chosen]
    chosen_ts = [int(df["TransactionDT"].iloc[c]) for c in chosen]
    # community detection on induced subgraph (depth-1 bipartite)
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    # Build entity list involved in expansion
    ents_in_expansion = set()
    for _, ent in detail["edges"]:
        ents_in_expansion.add((ent["entity_type"], ent["entity_key"]))
    # Add seed entities
    for ent in idx.seed_entities(pos):
        ents_in_expansion.add(ent)
    ents_list = sorted(ents_in_expansion)
    ent_of = {e: i for i, e in enumerate(ents_list)}
    # bipartite edges: transaction -> entity
    # we have detail edges plus seed-entity edges (seed to each seed entity)
    for txn_pos in chosen:
        for etype, ekey in idx.seed_entities(txn_pos) if txn_pos in [pos] + detail["chosen_positions"] else []:
            # But this would include entities of non-seed neighbors which may have edges to other txns
            pass
    # Simpler: For community, we consider transaction-transaction connectivity via shared entity within chosen set
    # Build transaction-entity incidence for chosen set: each chosen txn's entities that are in ents_list
    txn_entities = {}
    for c in chosen:
        ents = idx.seed_entities(c)
        # filter to non-hub entities (already in index)
        filtered = [e for e in ents if e in ents_list]
        txn_entities[c] = filtered
    # If number of entities is 0, community is isolated
    n_txn = len(chosen)
    n_ent = len(ents_list)
    n_total = n_txn + n_ent
    rows, cols = [], []
    # map chosen txn positions to 0..n_txn-1
    pos_to_idx = {p: i for i, p in enumerate(chosen)}
    for txn_pos, ents in txn_entities.items():
        ti = pos_to_idx[txn_pos]
        for e in ents:
            ei = ent_of[e]
            rows.append(ti); cols.append(n_txn + ei)
    if rows:
        adj = coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(n_total, n_total))
        n_c, labels = connected_components(adj + adj.T, directed=False)
    else:
        n_c, labels = 1, np.zeros(n_total, dtype=int)
    # community summary: all chosen txns belong to components; seed's component is what matters
    seed_idx = pos_to_idx[pos]
    seed_comp = int(labels[seed_idx])
    # members in seed component
    comp_txn_positions = [chosen[i] for i, lab in enumerate(labels[:n_txn]) if lab == seed_comp]
    comp_txn_ids = [int(df["TransactionID"].iloc[p]) for p in comp_txn_positions]
    # entity types in component
    comp_ents = [ents_list[i] for i, lab in enumerate(labels[n_txn:]) if lab == seed_comp] if n_ent>0 else []
    # summary
    # need risk scores if available
    try:
        from app.storage.db import connect
        conn = connect(s.db_path)
        # fetch scores for comp
        placeholders = ",".join(["?"]*len(comp_txn_ids)) if comp_txn_ids else "NULL"
        scores = {}
        if comp_txn_ids:
            rows_db = conn.execute(f"SELECT transaction_id, risk_score FROM risk_predictions WHERE transaction_id IN ({placeholders})", comp_txn_ids).fetchall()
            scores = {r[0]: r[1] for r in rows_db}
        conn.close()
    except Exception:  # noqa: BLE001 - community score lookup is best-effort
        scores = {}
    max_score = max([scores.get(tid, 0) for tid in comp_txn_ids], default=0)
    # time span
    if comp_txn_positions:
        ts_vals = [int(df["TransactionDT"].iloc[p]) for p in comp_txn_positions]
        span_hours = (max(ts_vals) - min(ts_vals)) / 3600 if len(ts_vals)>1 else 0
    else:
        span_hours = 0
    # counts
    ent_type_counts = {}
    for et, ek in comp_ents:
        ent_type_counts[et] = ent_type_counts.get(et, 0) + 1
    summary = {
        "transaction_count": len(comp_txn_ids),
        "entity_count": len(comp_ents),
        "entity_type_counts": ent_type_counts,
        "time_span_hours": round(float(span_hours),2),
        "hub_pruned_count": sum(1 for pr in detail["pruning"] if pr.get("pruned")),
        "max_risk_score": round(float(max_score),4),
        "seed_component_id": seed_comp,
        "n_components_total": int(n_c),
    }
    # Build nodes/edges for visualization contract
    nodes = []
    # transaction nodes
    for tid, ts in zip(chosen_ids, chosen_ts):
        nodes.append({"id": f"txn:{tid}", "type": "TRANSACTION", "transaction_id": tid, "ts": ts, "is_seed": tid==transaction_id, "risk_score": scores.get(tid)})
    for et, ek in ents_list:
        in_comp = (et, ek) in comp_ents
        nodes.append({"id": f"{et}:{ek}", "type": et, "entity_key": ek, "in_seed_component": in_comp})
    edges = []
    for txn_pos in chosen:
        tid = int(df["TransactionID"].iloc[txn_pos])
        for et, ek in idx.seed_entities(txn_pos):
            if (et, ek) in ents_list:
                edges.append({"source": f"txn:{tid}", "target": f"{et}:{ek}", "relationship_type": "HAS_ENTITY", "transaction_id": tid, "ts": int(df["TransactionDT"].iloc[txn_pos])})
    # model risk vs graph context separation
    # fetch seed risk
    seed_risk = scores.get(transaction_id)
    result = {
        "transaction_id": transaction_id,
        "graph_version": p["graph_version"],
        "params_hash": ph,
        "parameters": p,
        "seed": {"transaction_id": transaction_id, "ts": int(df["TransactionDT"].iloc[pos]), "risk_score": seed_risk, "model_version": None},
        "entities": [{"entity_type": et, "entity_key": ek} for et, ek in idx.seed_entities(pos)],
        "transactions": [{"transaction_id": tid, "ts": ts} for tid, ts in zip(chosen_ids, chosen_ts)],
        "edges": edges,
        "nodes": nodes,
        "community": {
            "members": comp_txn_ids,
            "member_count": len(comp_txn_ids),
            "entity_members": [{"entity_type": et, "entity_key": ek} for et, ek in comp_ents],
            "summary": summary,
            "all_components": int(n_c),
        },
        "pruning": detail["pruning"],
        "temporal_window": detail["window"],
        "model_risk": {"risk_score": seed_risk, "note": "model risk separate from graph context"},
        "graph_context": {"connected_transactions": len(chosen_ids), "connected_entities": len(ents_list), "community": summary},
    }
    _cache[cache_key] = result
    return result

def get_graph_context(transaction_id: int, params: dict | None = None, settings=None) -> dict:
    return expand_transaction(transaction_id, params, settings)
