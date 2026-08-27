# Round-2 relational features: entity-relative DEVIATION signals.
# Motivated by diagnostics (reports/graph_diagnostics.json): round-1 cumulative degrees act mainly as time proxies; their gain does not beat a shuffled control. Round 2 tests whether per-entity deviation from learned history carries alignment-specific signal:
#   card_amt_z / dev_amt_z      Welford z-score vs entity's prior amounts
#   card_hour_dev / dev_hour_dev  circular distance to entity's mean hour
#   card_burst_24h              prior-24h velocity / sqrt(prior count)
#   pair_new_dev_card           device-card pairing unseen before -> 0, else log1p(prior co-occurrence count)
#   pair_new_addr_card          same for address-card pairs
# All strictly causal; missing entities -> NaN. Explicitly labeled POST-HOC exploration (round 2).

import numpy as np
import pandas as pd

from src.features.graph_features import _keys_array, _clean

TWO_PI = 2.0 * np.pi


class _Welford:
    __slots__ = ("n", "mean", "m2")

    def __init__(self):
        self.n = 0
        self.mean = 0.0
        self.m2 = 0.0


def _amt_z(w: _Welford, x):
    if w.n == 0:
        return np.nan
    sd = np.sqrt(max(w.m2 / w.n, 1e-9))
    return float((x - w.mean) / max(sd, 1e-3))


def _absorb_amt(w: _Welford, x):
    w.n += 1
    d = x - w.mean
    w.mean += d / w.n
    w.m2 += d * (x - w.mean)


class _Hour:
    __slots__ = ("cx", "cy", "n")

    def __init__(self):
        self.cx = 0.0
        self.cy = 0.0
        self.n = 0


def _hour_dist(h: _Hour, theta):
    if h.n == 0:
        return np.nan
    phi = np.arctan2(h.cy / h.n, h.cx / h.n)
    d = abs(theta - phi) % TWO_PI
    d = min(d, TWO_PI - d)
    return float(d / np.pi)


def build_deviation_features(full_txn: pd.DataFrame, merged: pd.DataFrame,
                             device_col: str = "device_id"):
    """DataFrame aligned to merged's rows, columns:

    card_amt_z, card_hour_dev, card_burst_24h,
    dev_amt_z, dev_hour_dev, pair_new_dev_card, pair_new_addr_card
    """
    # ---------------- card-level over the FULL stream -------------------
    full = full_txn.reset_index(drop=True)
    pos_of_tid = pd.Series(full.index, index=full["TransactionID"].values)
    fi = full.sort_values("TransactionDT", kind="mergesort").index
    fs = full.loc[fi]
    t_arr = fs["TransactionDT"].to_numpy()
    k_arr = _keys_array(fs["card1"])
    a_arr = fs["TransactionAmt"].to_numpy(dtype="float64")
    th_arr = ((t_arr % 86400) // 3600) * (TWO_PI / 24.0)

    wf, hr, cnt, recent = {}, {}, {}, {}
    out = np.full((len(fs), 3), np.nan)
    for i in range(len(fs)):
        k = _clean(k_arr[i])
        if k is None:
            continue
        t = int(t_arr[i])
        c0 = cnt.get(k, 0)
        lst = recent.get(k)
        v24 = 0
        if lst:
            lo = 0
            while lo < len(lst) and lst[lo] < t - 86400:
                lo += 1
            del lst[:lo]
            v24 = len(lst)
        w = wf.setdefault(k, _Welford())
        h = hr.setdefault(k, _Hour())
        out[i] = (
            _amt_z(w, a_arr[i]) if w.n else np.nan,
            _hour_dist(h, th_arr[i]),
            float(v24 / np.sqrt(c0)) if c0 > 0 else np.nan,
        )
        _absorb_amt(w, a_arr[i])
        h.cx += np.cos(th_arr[i]); h.cy += np.sin(th_arr[i]); h.n += 1
        cnt[k] = c0 + 1
        recent.setdefault(k, []).append(t)

    ca = pd.DataFrame(out, index=fs.index,
                      columns=["card_amt_z", "card_hour_dev",
                               "card_burst_24h"]).sort_index()
    ca = ca.iloc[pos_of_tid.reindex(merged["TransactionID"].values)
                 .to_numpy()]
    ca.index = merged.index

    # ------------- device + pair level over merged rows -----------------
    m = merged[["TransactionID", "TransactionDT", "TransactionAmt",
                "card1", "addr1", device_col]].reset_index(drop=True)
    mi = m.sort_values("TransactionDT", kind="mergesort").index
    ms = m.loc[mi]
    t2 = ms["TransactionDT"].to_numpy()
    kd = _keys_array(ms[device_col])
    ka = _keys_array(ms["card1"])
    kr = _keys_array(ms["addr1"])
    am2 = ms["TransactionAmt"].to_numpy(dtype="float64")
    th2 = ((t2 % 86400) // 3600) * (TWO_PI / 24.0)

    wfd, hrd, pdc, pac = {}, {}, {}, {}
    o2 = np.full((len(ms), 4), np.nan)
    for i in range(len(ms)):
        dev, card, addr = _clean(kd[i]), _clean(ka[i]), _clean(kr[i])
        row = [np.nan] * 4
        if dev is not None:
            wd = wfd.setdefault(dev, _Welford())
            row[0] = _amt_z(wd, am2[i]) if wd.n else np.nan
            hd = hrd.setdefault(dev, _Hour())
            row[1] = _hour_dist(hd, th2[i])
        if dev is not None and card is not None:
            key = (dev, card)
            row[2] = 0.0 if key not in pdc else float(np.log1p(pdc[key]))
            pdc[key] = pdc.get(key, 0) + 1
        if addr is not None and card is not None:
            key = (addr, card)
            row[3] = 0.0 if key not in pac else float(np.log1p(pac[key]))
            pac[key] = pac.get(key, 0) + 1
        o2[i] = row
        if dev is not None:
            _absorb_amt(wfd[dev], am2[i])
            hd = hrd[dev]
            hd.cx += np.cos(th2[i]); hd.cy += np.sin(th2[i]); hd.n += 1

    dv = pd.DataFrame(o2, index=ms.index,
                      columns=["dev_amt_z", "dev_hour_dev",
                               "pair_new_dev_card",
                               "pair_new_addr_card"]).sort_index()
    dv.index = merged.index
    return pd.concat([ca, dv], axis=1)
