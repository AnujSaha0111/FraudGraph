# Batch scorer — idempotent, version-aware
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from app.data.splits import chronological_split
from app.features.base import BaseFeaturePipeline
from app.risk.scorer import RiskScorer
from app.storage.db import connect


def batch_score(data_proc: Path, model_dir: Path, db_path: Path, reports: Path) -> dict:
    # Score all production rows and persist to DuckDB risk_predictions
    t0 = time.perf_counter()
    df = pd.read_parquet(data_proc / "experiment_base.parquet")
    prod = pd.read_parquet(data_proc / "production_features.parquet")
    prod_indexed = prod.set_index("TransactionID")
    # build matrix using same logic as training
    with open(reports / "temporal_analysis.json") as f:
        ta = json.load(f)
    split = chronological_split(df, ta["split_dt_train_end"], ta["split_dt_valid_end"])
    pipe = BaseFeaturePipeline().fit(df.loc[split.train])
    X_base = pipe.transform(df)
    rel_cols = ["amt_z_card","amt_z_device","hour_dev_card","hour_dev_device","hours_since_last_card","hours_since_last_device"]
    rel = prod_indexed.reindex(df["TransactionID"].values)[rel_cols].to_numpy(dtype="float32")
    X = np.column_stack([X_base, rel])

    scorer = RiskScorer(model_dir=model_dir)
    scores = scorer.score_matrix(X)

    # persist - bulk via DataFrame registration (fast)
    conn = connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS risk_predictions(
            transaction_id BIGINT,
            model_version VARCHAR,
            risk_score DOUBLE,
            risk_band VARCHAR,
            scored_at TIMESTAMP,
            PRIMARY KEY (transaction_id, model_version)
        )
    """)
    # prepare DataFrame for bulk insert, deduplicate by (transaction_id, model_version)
    bands = [scorer.band(float(s)) for s in scores]
    out_df = pd.DataFrame({
        "transaction_id": df["TransactionID"].to_numpy(),
        "model_version": scorer.model_version,
        "risk_score": scores.astype(float),
        "risk_band": bands,
    })
    # Use DuckDB's INSERT OR REPLACE via anti-join + append or delete+insert for idempotency
    # Delete existing rows for this model_version then insert
    conn.execute("DELETE FROM risk_predictions WHERE model_version = ?", [scorer.model_version])
    conn.register("out_df", out_df)
    conn.execute("INSERT INTO risk_predictions SELECT transaction_id, model_version, risk_score, risk_band, NOW() FROM out_df")
    conn.unregister("out_df")
    conn.close()
    dt = time.perf_counter() - t0
    return {
        "model_version": scorer.model_version,
        "rows_scored": len(out_df),
        "batch_seconds": round(dt, 2),
        "rows_per_sec": round(len(out_df)/dt, 1) if dt>0 else None,
        "mean_score": round(float(scores.mean()), 4),
        "scored_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
