# Model training — 432 base + 6 validated relational (438 cols), frozen XGBoost params.
import hashlib
import json
import subprocess
import time
from pathlib import Path

import numpy as np
import pandas as pd

from app.data.splits import chronological_split
from app.features.base import FREQ_CATS, NUMERIC_BASE, BaseFeaturePipeline
from src.models.baselines import xgb_params
from src.models.metrics import best_f1_threshold, full_metrics

RELATIONAL_INCLUDED = [
    "amt_z_card", "amt_z_device", "hour_dev_card", "hour_dev_device",
    "hours_since_last_card", "hours_since_last_device",
]

def _git_sha() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[2], text=True).strip()
    except Exception:  # noqa: BLE001 - git may be unavailable; sha is optional metadata
        return None

def _manifest_hash(included: list[str]) -> str:
    return hashlib.md5(",".join(included).encode()).hexdigest()[:12]

def feature_names_in_order() -> list[str]:
    """432 base (pipeline order) + 6 relational (manifest order)."""
    # BaseFeaturePipeline order is: logTransactionAmt, NUMERIC_BASE, then FREQ_CATS
    # with M1..M9 kept as M-names rather than freq_M.
    corrected = []
    for c in FREQ_CATS:
        if c.startswith("M"):
            corrected.append(c)
        else:
            corrected.append(f"freq_{c}")
    names = ["logTransactionAmt"] + NUMERIC_BASE + corrected
    return names + RELATIONAL_INCLUDED

def build_feature_matrix(df: pd.DataFrame, train_mask: np.ndarray, production_features_path: Path) -> tuple[np.ndarray, list[str]]:
    """Return X (438 cols) and feature_names in frozen order."""
    pipe = BaseFeaturePipeline().fit(df.loc[train_mask])
    X_base = pipe.transform(df)  # 432
    prod = pd.read_parquet(production_features_path)
    # align by TransactionID
    prod_indexed = prod.set_index("TransactionID")
    rel = prod_indexed.reindex(df["TransactionID"].values)[RELATIONAL_INCLUDED].to_numpy(dtype="float32")
    X = np.column_stack([X_base, rel])
    names = feature_names_in_order()
    assert X.shape[1] == len(names) == 438, f"{X.shape} vs {len(names)}"
    assert names[-6:] == RELATIONAL_INCLUDED
    return X, names, pipe

def train_and_evaluate(data_proc: Path, reports: Path, model_dir: Path, seed: int = 42) -> dict:
    df = pd.read_parquet(data_proc / "experiment_base.parquet")
    with open(reports / "temporal_analysis.json") as f:
        ta = json.load(f)
    split = chronological_split(df, ta["split_dt_train_end"], ta["split_dt_valid_end"])
    y = df["isFraud"].to_numpy()

    X, feature_names, pipe = build_feature_matrix(df, split.train, data_proc / "production_features.parquet")

    clf = xgb_params(seed)
    t0 = time.perf_counter()
    clf.fit(X[split.train], y[split.train], eval_set=[(X[split.valid], y[split.valid])], verbose=False)
    fit_s = time.perf_counter() - t0

    # predictions
    p_valid = clf.predict_proba(X[split.valid])[:, 1]
    p_test = clf.predict_proba(X[split.test])[:, 1]
    thr = best_f1_threshold(y[split.valid], p_valid)
    mt = full_metrics(y[split.test], p_test, thr)
    mv = full_metrics(y[split.valid], p_valid, thr)

    # versioning
    manifest_hash = _manifest_hash(RELATIONAL_INCLUDED)
    model_version = f"fraud_xgb_v1-{manifest_hash[:7]}"
    git_sha = _git_sha()
    params = clf.get_params()

    metadata = {
        "model_version": model_version,
        "feature_count": len(feature_names),
        "feature_names": feature_names,
        "relational_features": RELATIONAL_INCLUDED,
        "relational_version": manifest_hash,
        "feature_manifest_path": "reports/feature_manifest.json",
        "training_dataset": "data/processed/experiment_base.parquet + data/processed/production_features.parquet",
        "split": {"train_end": float(ta["split_dt_train_end"]), "valid_end": float(ta["split_dt_valid_end"]), "rows": {"train": int(split.train.sum()), "valid": int(split.valid.sum()), "test": int(split.test.sum())}},
        "seed": seed,
        "xgboost_params": {k: str(v) if isinstance(v, (type,)) else v for k, v in params.items()},
        "n_estimators_trained": int(clf.n_estimators),
        "best_iteration": int(getattr(clf, "best_iteration", -1)) if hasattr(clf, "best_iteration") else None,
        "objective": "binary:logistic",
        "eval_metric": "aucpr",
        "threshold": float(thr),
        "metrics_test": mt,
        "metrics_valid": mv,
        "git_sha": git_sha,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "base_feature_count": 432,
        "relational_feature_count": 6,
        "fit_seconds": round(fit_s, 2),
    }
    # persist
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / f"{model_version}.json"
    meta_path = model_dir / f"{model_version}.metadata.json"
    clf.save_model(str(model_path))
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)
    # also save as latest symlink/copy
    latest_model = model_dir / "latest.json"
    latest_meta = model_dir / "latest.metadata.json"
    # copy
    import shutil
    shutil.copy(model_path, latest_model)
    shutil.copy(meta_path, latest_meta)

    # also save feature order sidecar for strict validation
    with open(model_dir / f"{model_version}.features.json", "w") as f:
        json.dump(feature_names, f, indent=1)

    result = {
        "model_version": model_version,
        "model_path": str(model_path),
        "metadata_path": str(meta_path),
        "feature_names": feature_names,
        "metrics_test": mt,
        "metrics_valid": mv,
        "fit_seconds": fit_s,
        "predictions_test": p_test,
        "X_test": X[split.test],
        "y_test": y[split.test],
        "clf": clf,
        "metadata": metadata,
        "pipe": pipe,
    }
    return result
