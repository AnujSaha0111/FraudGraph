# Baseline models (LR, XGBoost) on identical temporal splits.

# Feature policy (fixed a priori, identical for Model A and Model B):
# - numeric block: TransactionAmt(log), dist1/2, C1-C14, D1-D15, V1-V339,
# - id_01-id_11, hour, dow, card2/3/5, addr1/addr2 raw codes;
# - categorical block: frequency-encoded on TRAIN PERIOD ONLY (ProductCD, card4, card6, card1, addr1, P/R_emaildomain, DeviceType, M1-M9, id_12-id_38);
# - Model B adds ONLY the 24 causal graph features.

import numpy as np
import pandas as pd

NUMERIC_BASE = (
    ["TransactionAmt", "dist1", "dist2", "addr1", "addr2",
     *[f"C{i}" for i in range(1, 15)], *[f"D{i}" for i in range(1, 16)],
     *[f"V{i}" for i in range(1, 340)],
     *[f"id_{i:02d}" for i in range(1, 12)], "hour", "dow", "card2",
     "card3", "card5"]
)
FREQ_CATS = ["ProductCD", "card4", "card6", "card1", "P_emaildomain",
             "R_emaildomain", "DeviceType",
             *[f"M{i}" for i in range(1, 10)],
             *[f"id_{i:02d}" for i in range(12, 39)]]

GRAPH_COLS = None


def m1m9_to_num(s):
    return s.map({"T": 1.0, "F": 0.0}).astype("float32")


def build_matrix(df, train_mask, use_graph=False):
    """Return (X, feature_names). Frequency stats fit on train_mask rows."""
    parts = []
    names = []
    amt = np.log1p(df["TransactionAmt"].to_numpy(dtype="float64"))
    parts.append(amt.astype("float32"))
    names.append("logTransactionAmt")
    num = df[[c for c in NUMERIC_BASE if c != "TransactionAmt"]].astype(
        "float32")
    parts.append(num.to_numpy())
    names += list(num.columns)

    tr = df.loc[train_mask]
    for c in FREQ_CATS:
        s = df[c]
        if c.startswith("M"):
            s = m1m9_to_num(s)
            parts.append(s.to_numpy())
            names.append(c)
            continue
        cnt = tr[c].value_counts(normalize=True)
        fe = s.map(cnt).fillna(-1.0).astype("float32").to_numpy()
        parts.append(fe)
        names.append(f"freq_{c}")
    X = np.column_stack(parts)
    if use_graph:
        g = df[GRAPH_COLS].to_numpy(dtype="float32")
        X = np.column_stack([X, g])
        names += list(GRAPH_COLS)
    return X, names


def xgb_params(seed):
    from xgboost import XGBClassifier
    return XGBClassifier(
        n_estimators=600, learning_rate=0.05, max_depth=7,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
        reg_lambda=1.0, tree_method="hist", n_jobs=-1,
        eval_metric="aucpr", early_stopping_rounds=50, random_state=seed,
        base_score=0.05,
    )
