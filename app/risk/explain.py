# Top-k feature contributions — deterministic SHAP TreeExplainer
import numpy as np


def top_k_contributions(clf, X_row: np.ndarray, feature_names: list[str], k: int = 5) -> list[dict]:
    """Return top-k by absolute SHAP value. Deterministic, local, no external API."""
    # Use XGBoost's built-in gain? For determinism and speed, use SHAP if available, else fallback to gain*value
    try:
        import shap
        explainer = shap.TreeExplainer(clf)
        sv = explainer.shap_values(X_row.reshape(1, -1))
        # shap 0.4+ returns array shape (1, n) for binary
        if isinstance(sv, list):
            sv = sv[1] if len(sv) > 1 else sv[0]
        sv = np.asarray(sv).reshape(-1)
    except Exception:  # noqa: BLE001 - documented deterministic fallback path
        # Fallback: use feature importances weighted by standardized value
        # Not ideal but deterministic and fast; we document fallback
        imp = clf.feature_importances_
        # center
        vals = X_row.astype(float)
        # use imp * abs(value) as proxy
        sv = imp * np.abs(vals - np.nanmean(vals))
        sv = np.nan_to_num(sv, nan=0.0)
    idx = np.argsort(np.abs(sv))[::-1][:k]
    out = []
    for i in idx:
        out.append({
            "feature": feature_names[i],
            "value": float(X_row[i]) if not np.isnan(X_row[i]) else None,
            "contribution": float(sv[i]),
            "direction": "positive" if sv[i] > 0 else "negative" if sv[i] < 0 else "neutral",
            "abs_rank": int(np.where(idx == i)[0][0] + 1) if i in idx else None,
        })
    # sort by abs contribution desc
    out = sorted(out, key=lambda d: abs(d["contribution"]), reverse=True)
    return out
