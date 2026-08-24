# Fraud metric suite: PR-AUC primary, plus operating-point metrics
import numpy as np
from sklearn.metrics import (average_precision_score, roc_auc_score,
                             precision_score, recall_score, f1_score,
                             confusion_matrix)


def precision_at_k(y_true, scores, k_frac):
    n = len(scores)
    k = max(1, int(round(n * k_frac)))
    idx = np.argsort(-scores)[:k]
    return float(np.asarray(y_true)[idx].mean())


def recall_at_k(y_true, scores, k_frac):
    y = np.asarray(y_true)
    n = len(scores)
    k = max(1, int(round(n * k_frac)))
    idx = np.argsort(-scores)[:k]
    return float(y[idx].sum() / max(y.sum(), 1))


def best_f1_threshold(y_true, scores):
    """Sweep candidate thresholds from score quantiles; return argmax-F1."""
    y = np.asarray(y_true)
    qs = np.quantile(scores, np.linspace(0.80, 0.9995, 200))
    cands = np.unique(qs)
    best_t, best_f = 0.5, -1.0
    for t in cands:
        pred = (scores >= t).astype(int)
        if pred.sum() == 0:
            continue
        f = f1_score(y, pred, zero_division=0)
        if f > best_f:
            best_f, best_t = f, t
    return float(best_t)


def full_metrics(y_true, scores, threshold=None, k_fracs=(0.01, 0.001)):
    y = np.asarray(y_true)
    s = np.asarray(scores)
    out = {
        "n": int(len(y)),
        "positives": int(y.sum()),
        "pr_auc": float(average_precision_score(y, s)),
        "roc_auc": float(roc_auc_score(y, s)),
    }
    for kf in k_fracs:
        out[f"precision_at_{kf}"] = round(precision_at_k(y, s, kf), 5)
        out[f"recall_at_{kf}"] = round(recall_at_k(y, s, kf), 5)
    if threshold is not None:
        pred = (s >= threshold).astype(int)
        out["threshold"] = float(threshold)
        out["precision"] = float(precision_score(y, pred, zero_division=0))
        out["recall"] = float(recall_score(y, pred, zero_division=0))
        out["f1"] = float(f1_score(y, pred, zero_division=0))
        tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
        out["confusion"] = {"tn": int(tn), "fp": int(fp),
                            "fn": int(fn), "tp": int(tp)}
    return out
