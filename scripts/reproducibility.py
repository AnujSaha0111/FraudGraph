# Model reproducibility check.
# Loads the persisted XGBoost artifact, scores a fixed fixture, repeats, and verifies equivalence. Writes reports/reproducibility.json.

import json
import hashlib
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from app.risk.registry import load_model


def main():
    model_dir = Path("models")
    # Fixed fixture: 10 rows, 438 cols, deterministic seed
    rng = np.random.RandomState(42)
    X = rng.randn(10, 438).astype("float32")
    X = np.nan_to_num(X, nan=0.0)

    clf, meta, feats = load_model("latest")
    # First scoring
    t0 = time.perf_counter()
    p1 = clf.predict_proba(X)[:, 1].astype(float)
    t1 = time.perf_counter() - t0

    # Second scoring (reload)
    clf2, meta2, feats2 = load_model("latest")
    p2 = clf2.predict_proba(X)[:, 1].astype(float)

    max_diff = float(np.max(np.abs(p1 - p2)))
    mean_diff = float(np.mean(np.abs(p1 - p2)))
    equivalent = bool(np.allclose(p1, p2, equal_nan=True) and max_diff == 0.0)

    # Feature hash
    feat_hash = hashlib.sha256(",".join(feats).encode()).hexdigest()[:16]

    result = {
        "model_version": meta["model_version"],
        "feature_count": meta["feature_count"],
        "feature_hash": feat_hash,
        "feature_version": meta.get("relational_version"),
        "seed": meta.get("seed"),
        "split": meta.get("split"),
        "git_sha": meta.get("git_sha"),
        "metrics_test_pr_auc": meta.get("metrics_test", {}).get("pr_auc") if isinstance(meta.get("metrics_test"), dict) else None,
        "threshold": meta.get("threshold"),
        "reload_max_diff": max_diff,
        "reload_mean_diff": mean_diff,
        "reload_equivalent": equivalent,
        "fixture_rows": 10,
        "fixture_cols": 438,
        "latency_ms_first": round(t1 * 1000, 2),
        "pr_auc_ge_073": bool((meta.get("metrics_test", {}).get("pr_auc", 0) if isinstance(meta.get("metrics_test"), dict) else 0) >= 0.73) if isinstance(meta.get("metrics_test"), dict) else None,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    Path("reports").mkdir(exist_ok=True)
    Path("reports/reproducibility.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    assert equivalent, f"Reload not equivalent: max_diff={max_diff}"
    assert result["feature_count"] == 438
    assert feats == feats2
    print("Reproducibility: PASS")


if __name__ == "__main__":
    main()
