# Risk API — GET /transactions/{id}/risk and /risk/explanation
import json

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Request

from app.config import get_settings
from app.storage.db import connect

router = APIRouter(tags=["risk"])

def _load_matrices():
    settings = get_settings()
    df = pd.read_parquet(settings.processed_dir / "experiment_base.parquet")
    prod = pd.read_parquet(settings.processed_dir / "production_features.parquet")
    return df, prod

@router.get("/transactions/{transaction_id}/risk")
def get_risk(transaction_id: int, request: Request):
    settings = request.app.state.settings
    # check model available
    model_dir = settings.model_dir
    if not (model_dir / "latest.json").exists():
        raise HTTPException(status_code=503, detail="model unavailable")
    # check transaction exists — 404 if nowhere, 422 if exists in raw but not in production coverage
    df_path = settings.processed_dir / "experiment_base.parquet"
    raw_path = settings.processed_dir / "ieee_train_transaction.parquet"
    try:
        # check production coverage first
        prod_ids_check = set(pd.read_parquet(settings.processed_dir / "production_features.parquet", columns=["TransactionID"])["TransactionID"].values)
        if transaction_id in prod_ids_check:
            # exists and scorable
            pass
        else:
            # check if exists anywhere
            # try experiment_base then raw
            try:
                df_ids = set(pd.read_parquet(df_path, columns=["TransactionID"])["TransactionID"].values)
            except Exception:  # noqa: BLE001 - missing artifact treated as empty
                df_ids = set()
            if transaction_id in df_ids:
                # exists in joined but missing production (should not happen after batch)
                raise HTTPException(status_code=422, detail="transaction exists but cannot be scored under production contract (missing device/entity coverage)")
            # check raw
            try:
                raw_ids = set(pd.read_parquet(raw_path, columns=["TransactionID"])["TransactionID"].values)
            except Exception:  # noqa: BLE001 - unreadable raw store -> 503
                raise HTTPException(status_code=503, detail="storage unavailable") from None
            if transaction_id in raw_ids:
                raise HTTPException(status_code=422, detail="transaction exists but cannot be scored under production contract (missing device/entity coverage)")
            raise HTTPException(status_code=404, detail="transaction not found")
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 - any storage failure maps to 503
        raise HTTPException(status_code=503, detail="storage unavailable") from None
    prod_path = settings.processed_dir / "production_features.parquet"

    # try to read persisted score
    db_path = settings.db_path
    try:
        conn = connect(db_path)
        row = conn.execute("SELECT risk_score, risk_band, model_version FROM risk_predictions WHERE transaction_id = ?", [transaction_id]).fetchone()
        conn.close()
        if row:
            return {"transaction_id": transaction_id, "risk_score": float(row[0]), "risk_band": row[1], "model_version": row[2]}
    except Exception:  # noqa: BLE001, S110 - fallthrough to live scoring
        pass  # fallthrough to live scoring

    # live scoring fallback

    from app.data.splits import chronological_split
    from app.features.base import BaseFeaturePipeline
    from app.risk.scorer import RiskScorer
    scorer = RiskScorer(model_dir=model_dir)
    # Build single row matrix
    df_full = pd.read_parquet(df_path)
    prod_full = pd.read_parquet(prod_path)
    # need to build full matrices to get ordering; we can reuse training logic for single row
    with open(settings.reports_dir / "temporal_analysis.json") as f:
        ta = json.load(f)
    split = chronological_split(df_full, ta["split_dt_train_end"], ta["split_dt_valid_end"])
    pipe = BaseFeaturePipeline().fit(df_full.loc[split.train])
    X_base_all = pipe.transform(df_full)
    # map txn to index
    idx = int(np.where(df_full["TransactionID"].values == transaction_id)[0][0])
    x_base = X_base_all[idx]
    # relational
    prod_indexed = prod_full.set_index("TransactionID")
    rel_vals = prod_indexed.loc[transaction_id, ["amt_z_card","amt_z_device","hour_dev_card","hour_dev_device","hours_since_last_card","hours_since_last_device"]].to_numpy(dtype="float32")
    X_row = np.concatenate([x_base, rel_vals])
    res = scorer.score_row(X_row, transaction_id)
    return {"transaction_id": res.transaction_id, "risk_score": res.risk_score, "risk_band": res.risk_band, "model_version": res.model_version}

@router.get("/transactions/{transaction_id}/risk/explanation")
def get_explanation(transaction_id: int, request: Request, k: int = 5):
    settings = request.app.state.settings
    model_dir = settings.model_dir
    if not (model_dir / "latest.json").exists():
        raise HTTPException(status_code=503, detail="model unavailable")
    # existence: 404 if not in raw, 422 if in raw but not in production coverage
    prod_path = settings.processed_dir / "production_features.parquet"
    raw_path = settings.processed_dir / "ieee_train_transaction.parquet"
    try:
        prod_ids = set(pd.read_parquet(prod_path, columns=["TransactionID"])["TransactionID"].values)
        if transaction_id in prod_ids:
            pass
        else:
            raw_ids = set(pd.read_parquet(raw_path, columns=["TransactionID"])["TransactionID"].values)
            if transaction_id in raw_ids:
                raise HTTPException(status_code=422, detail="transaction exists but cannot be explained under production contract")
            raise HTTPException(status_code=404, detail="transaction not found")
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 - any storage failure maps to 503
        raise HTTPException(status_code=503, detail="storage unavailable") from None

    import json

    from app.data.splits import chronological_split
    from app.features.base import BaseFeaturePipeline
    from app.risk.explain import top_k_contributions
    from app.risk.scorer import RiskScorer
    scorer = RiskScorer(model_dir=model_dir)
    df_path = settings.processed_dir / "experiment_base.parquet"
    df_full = pd.read_parquet(df_path)
    prod_full = pd.read_parquet(prod_path)
    with open(settings.reports_dir / "temporal_analysis.json") as f:
        ta = json.load(f)
    split = chronological_split(df_full, ta["split_dt_train_end"], ta["split_dt_valid_end"])
    pipe = BaseFeaturePipeline().fit(df_full.loc[split.train])
    X_base_all = pipe.transform(df_full)
    idx = int(np.where(df_full["TransactionID"].values == transaction_id)[0][0])
    x_base = X_base_all[idx]
    prod_indexed = prod_full.set_index("TransactionID")
    rel_vals = prod_indexed.loc[transaction_id, ["amt_z_card","amt_z_device","hour_dev_card","hour_dev_device","hours_since_last_card","hours_since_last_device"]].to_numpy(dtype="float32")
    X_row = np.concatenate([x_base, rel_vals])
    score = float(scorer.score_matrix(X_row.reshape(1,-1))[0])
    contribs = top_k_contributions(scorer.clf, X_row, scorer.feature_names, k=k)
    return {"transaction_id": transaction_id, "risk_score": score, "risk_band": scorer.band(score), "model_version": scorer.model_version, "top_features": contribs}
