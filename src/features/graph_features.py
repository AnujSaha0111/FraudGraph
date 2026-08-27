# Causally-correct graph feature construction
# INVARIANT: every feature for a transaction at time T is derived only from transactions at strictly earlier positions in the time-sorted stream. No labels are ever used. Ties in TransactionDT keep original CSV order (stable sort); exact-tie transactions are NOT counted as prior.
# Entity streams:
# - card1 / addr1 accumulate over the FULL transaction stream (590,540 rows): history exists even for rows lacking identity enrichment.
# - Device + cross-entity pair features accumulate over identity-enriched rows only (devices are only observable there).
# Missing entities yield NaN features (XGBoost-native sparsity).

from bisect import bisect_left

import numpy as np
import pandas as pd

CARD_WINDOWS_S = (3600, 86400, 604800)
ADDR_WINDOWS_S = (3600, 86400)
DEV_WINDOWS_S = (3600, 86400)


def _keys_array(s: pd.Series):
    """Object ndarray where missing -> None (handles pd.NA safely)."""
    if s.dtype == object or str(s.dtype) in ("string", "str"):
        return s.astype(object).where(s.notna(), None).to_numpy()
    return s.to_numpy()


def _clean(k):
    if k is None:
        return None
    if isinstance(k, float) and np.isnan(k):
        return None
    if hasattr(k, "item"):
        try:
            if np.isnan(k):
                return None
        except (TypeError, ValueError):
            pass
        return k.item()
    return k


class _EntityState:
    def __init__(self, windows_s):
        self.windows = windows_s
        self.count = {}
        self.last_t = {}
        self.ts = {}
        self.amt_sum = {}

    def step(self, t, key, amt=None):
        if key is None:
            return tuple([np.nan] * (len(self.windows) + 3))
        c = self.count.get(key, 0)
        ts = self.ts.get(key)
        if c == 0:
            vel = [0.0] * len(self.windows)
            res = (0.0, *vel, np.nan,
                   np.nan)
        else:
            base = bisect_left(ts, t)
            vel = [float(base - bisect_left(ts, t - w)) for w in self.windows]
            recency = (t - self.last_t[key]) / 3600.0
            amean = (self.amt_sum[key] / c) if amt is not None else np.nan
            res = (float(c), *vel, recency, amean)
        self.count[key] = c + 1
        if c == 0:
            self.ts[key] = [t]
        else:
            self.ts[key].append(t)
        self.last_t[key] = t
        if amt is not None:
            self.amt_sum[key] = self.amt_sum.get(key, 0.0) + amt
        return res


class _PairState:
    def __init__(self):
        self.a2b = {}
        self.b2a = {}

    def step(self, a, b):
        da = len(self.a2b.get(a, ()))
        db = len(self.b2a.get(b, ()))
        self.a2b.setdefault(a, set()).add(b)
        self.b2a.setdefault(b, set()).add(a)
        return float(da), float(db)


def _entity_block(df_sorted, col, prefix, windows_s, use_amt):
    st = _EntityState(windows_s)
    times = df_sorted["TransactionDT"].to_numpy()
    keys = _keys_array(df_sorted[col])
    amounts = df_sorted["TransactionAmt"].to_numpy() if use_amt else None
    out = np.empty((len(df_sorted), len(windows_s) + 3))
    for i in range(len(df_sorted)):
        k = _clean(keys[i])
        amt = float(amounts[i]) if use_amt else None
        out[i] = st.step(int(times[i]), k, amt)
    cols = [f"{prefix}_tx_prior",
            *[f"{prefix}_tx_prior_{w // 3600}h" for w in windows_s],
            f"{prefix}_hours_since_last", f"{prefix}_amt_prior_mean"]
    return pd.DataFrame(out, index=df_sorted.index, columns=cols)


def _pair_block(df_sorted, cola, colb, name_a, name_b):
    st = _PairState()
    ka = _keys_array(df_sorted[cola])
    kb = _keys_array(df_sorted[colb])
    out = np.full((len(df_sorted), 2), np.nan)
    for i in range(len(df_sorted)):
        a, b = _clean(ka[i]), _clean(kb[i])
        if a is None or b is None:
            continue
        d_ab, d_ba = st.step(a, b)
        out[i, 0], out[i, 1] = d_ab, d_ba
    cols = [f"{name_a}_distinct_{name_b}_prior",
            f"{name_b}_distinct_{name_a}_prior"]
    return pd.DataFrame(out, index=df_sorted.index, columns=cols)


def build_graph_features(full_txn: pd.DataFrame, merged: pd.DataFrame,
                         device_col: str = "device_id") -> pd.DataFrame:
    """All graph features aligned to `merged`'s rows."""
    full = full_txn.reset_index(drop=True)
    pos_of_tid = pd.Series(full.index, index=full["TransactionID"].values)

    fsort_idx = full.sort_values("TransactionDT", kind="mergesort").index
    fsorted = full.loc[fsort_idx]

    ca = pd.concat([
        _entity_block(fsorted, "card1", "card", CARD_WINDOWS_S, True),
        _entity_block(fsorted, "addr1", "addr", ADDR_WINDOWS_S, True),
    ], axis=1)
    # restore original positional order, then select merged rows
    ca = ca.sort_index()
    mpos = pos_of_tid.reindex(merged["TransactionID"].values).to_numpy()
    ca = ca.iloc[mpos]
    ca.index = merged.index

    m = merged[["TransactionID", "TransactionDT", "TransactionAmt",
                "card1", "addr1", device_col]].reset_index(drop=True)
    msort_idx = m.sort_values("TransactionDT", kind="mergesort").index
    msorted = m.loc[msort_idx]
    dv = pd.concat([
        _entity_block(msorted, device_col, "dev", DEV_WINDOWS_S, True),
        _pair_block(msorted, device_col, "card1", "dev", "card"),
        _pair_block(msorted, device_col, "addr1", "dev", "addr"),
        _pair_block(msorted, "addr1", "card1", "addr", "card"),
    ], axis=1).sort_index()
    dv.index = merged.index

    feats = pd.concat([ca, dv], axis=1)
    feats["has_device"] = merged[device_col].notna().astype("int8")
    feats["has_addr"] = merged["addr1"].notna().astype("int8")
    return feats
