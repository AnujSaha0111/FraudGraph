# Can the pipeline recover KNOWN coordinated structures?
# Task 1  structural recovery: strong-tie graph (shared device OR shared instrument between accounts) -> connected components (scipy csgraph) vs ground-truth ring membership.
# Task 2  supervised detection: XGBoost base vs + causal relational features, temporal split, PR-AUC / recall@1% on ring transactions.
# Outputs: reports/synthetic_results.json (+ console tables)

import json
import sys

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

sys.path.insert(0, ".")
from src.config import DATA_SYNTH, REPORTS
from src.features.graph_features import _entity_block, _pair_block
from src.models.metrics import best_f1_threshold, full_metrics

DEV_WIN = (3600, 86400)


def strong_tie_components(df):
    """Accounts connected if they ever shared a device or instrument."""
    acct_ids = sorted(df["customer"].unique())
    aidx = {a: i for i, a in enumerate(acct_ids)}
    pairs = set()
    for col in ("device", "instrument"):
        g = df.groupby(col)["customer"].agg(lambda s: sorted(set(s)))
        for key, members in g.items():
            if len(members) < 2:
                continue
            if str(key).startswith(("RD", "RI", "HH")) and len(members) > 8:
                print(f"  [debug] {key}: {len(members)} accounts")
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    pairs.add((members[i], members[j]))
    n = len(acct_ids)
    r = [aidx[a] for a, b in pairs]
    c = [aidx[b] for a, b in pairs]
    adj = coo_matrix((np.ones(len(r)), (r, c)), shape=(n, n))
    ncomp, lab = connected_components(adj + adj.T, directed=False)
    return acct_ids, lab, ncomp


def main():
    df, meta = json_gt_load()
    print("rows:", len(df), "ring txns:", int(df["is_ring"].sum()))

    # ---------------- Task 1: structural recovery ----------------------
    acct_ids, lab, ncomp = strong_tie_components(df)
    truth_acct_ring = {}
    for rid, m in meta.items():
        for a in m["accounts"]:
            truth_acct_ring[int(a)] = rid
    comp_members = {}
    for a, l in zip(acct_ids, lab):
        comp_members.setdefault(l, []).append(a)
    # score only components of size>=3 as 'predicted rings'
    recs = []
    for l, members in comp_members.items():
        if len(members) < 3:
            continue
        true_rings = [truth_acct_ring.get(m) for m in members]
        n_true = sum(1 for t in true_rings if t)
        purity = n_true / len(members)
        dom = pd.Series([t for t in true_rings if t]).mode()
        recs.append({"component": int(l), "size": len(members),
                     "ring_members": n_true, "purity": round(purity, 3),
                     "dominant_ring": str(dom.iloc[0]) if len(dom) else "-"})
    recs = pd.DataFrame(recs).sort_values("ring_members", ascending=False)
    print("\ncomponents size>=3:")
    print(recs.head(12).to_string(index=False))

    # ring-level recovery: dominant ring found by some component?
    recovery = {}
    for rid, m in meta.items():
        hit = recs[recs.dominant_ring == rid] if len(recs) else []
        recovered = bool(len(hit) and hit.iloc[0].purity >= 0.5)
        recovery[rid] = {"recovered": recovered,
                         "best_purity": float(hit.iloc[0].purity)
                         if len(hit) else None}
    print("\nrecovery:", json.dumps(recovery))

    # ---------------- Task 2: supervised detection ---------------------
    d = df.rename(columns={"t_sec": "TransactionDT", "amount":
                           "TransactionAmt"})
    y = df["is_ring"].to_numpy()
    q70, q85 = np.quantile(d["TransactionDT"], [0.70, 0.85])
    tr, va, te = (d.TransactionDT.to_numpy() < q70,
                  (d.TransactionDT >= q70) & (d.TransactionDT < q85),
                  d.TransactionDT >= q85)

    gf = pd.concat([
        _entity_block(d, "device", "dev", DEV_WIN, True),
        _entity_block(d, "instrument", "inst", DEV_WIN, True),
        _pair_block(d, "device", "instrument", "dev", "inst"),
    ], axis=1)

    tr_cnt_dev = pd.Series(d.loc[tr, "device"]).value_counts()
    tr_cnt_merch = pd.Series(d.loc[tr, "merchant"]).value_counts()
    base = pd.DataFrame({
        "log_amt": np.log1p(d["TransactionAmt"].to_numpy()),
        "hour": d["hour"].to_numpy(), "dow": d["dow"].to_numpy(),
        "freq_device": d["device"].map(tr_cnt_dev).fillna(-1).to_numpy(),
        "freq_merchant": d["merchant"].map(tr_cnt_merch).fillna(-1).to_numpy(),
    }).astype("float32")

    XB, XG = base.to_numpy(), pd.concat([base, gf], axis=1).to_numpy()\
        .astype("float32")
    from xgboost import XGBClassifier
    out = {"structural_recovery": recovery,
           "n_components_ge3": len(recs)}
    for tag, X in (("XGB_base", XB), ("XGB_graph", XG)):
        clf = XGBClassifier(n_estimators=400, learning_rate=0.08,
                            max_depth=6, subsample=0.85, colsample_bytree=.85,
                            tree_method="hist", n_jobs=-1,
                            eval_metric="aucpr", early_stopping_rounds=40,
                            random_state=42, base_score=0.02)
        clf.fit(X[tr], y[tr], eval_set=[(X[va], y[va])], verbose=False)
        sv = clf.predict_proba(X[va])[:, 1]
        st = clf.predict_proba(X[te])[:, 1]
        thr = best_f1_threshold(y[va], sv)
        mt = full_metrics(y[te], st, thr)
        out[tag] = {k: v for k, v in mt.items() if k != "confusion"}
        out[tag]["confusion"] = mt["confusion"]
        print(f"{tag}: test PR-AUC {mt['pr_auc']:.4f} "
              f"recall@1% {mt['recall_at_0.01']:.3f}")

    with open(REPORTS / "synthetic_results.json", "w") as f:
        json.dump(out, f, indent=2, default=str)
    recs.to_csv(REPORTS / "synthetic_components.csv", index=False)


def json_gt_load():
    df = pd.read_parquet(DATA_SYNTH / "synthetic_transactions.parquet")
    meta = json.load(open(DATA_SYNTH / "ring_ground_truth.json"))
    return df, meta


if __name__ == "__main__":
    main()
