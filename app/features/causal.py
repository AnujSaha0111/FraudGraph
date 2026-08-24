# Causal relational feature engine (productized from the validated research algorithms: src/features/graph_features.py + src/features/deviation_features.py).

# Invariants (enforced by tests/test_features_causal.py):
# - strict causality: state is read BEFORE the current row is absorbed; exact timestamp ties are never treated as prior;
# - half-open windows [t-W, t);
# - no cumulative degree / lifetime distinct-partner outputs (banned family): every window is bounded; the only lifetime quantity exposed is a pairwise co-occurrence count (novelty continuum), which the shuffled-control gate validated as alignment-specific and which is not a degree measure.

import math
from bisect import bisect_left

import numpy as np
import pandas as pd

from app.features.contract import FEATURE_NAMES, FEATURE_REGISTRY, RelationalInputColumns

_TWO_PI = 2.0 * math.pi


def _clean(key):
    if key is None:
        return None
    try:
        if bool(pd.isna(key)):
            return None
    except (TypeError, ValueError):
        pass
    return str(key)


class _Welford:
    __slots__ = ("m2", "mean", "n")

    def __init__(self):
        self.n = 0
        self.mean = 0.0
        self.m2 = 0.0

    def z(self, x, min_history: int) -> float:
        if self.n < min_history:
            return math.nan
        sd = math.sqrt(max(self.m2 / self.n, 1e-9))
        return float((x - self.mean) / max(sd, 1e-3))

    def absorb(self, x) -> None:
        self.n += 1
        d = x - self.mean
        self.mean += d / self.n
        self.m2 += d * (x - self.mean)


class _CircularHour:
    __slots__ = ("cx", "cy", "n")

    def __init__(self):
        self.cx = 0.0
        self.cy = 0.0
        self.n = 0

    def distance(self, theta) -> float:
        if self.n == 0:
            return math.nan
        phi = math.atan2(self.cy / self.n, self.cx / self.n)
        d = abs(theta - phi) % _TWO_PI
        return float(min(d, _TWO_PI - d) / math.pi)

    def absorb(self, theta) -> None:
        self.cx += math.cos(theta)
        self.cy += math.sin(theta)
        self.n += 1


# output-column templates per entity role (must match FEATURE_REGISTRY names)
_ENTITY_OUTPUTS = {
    "card": ("amt_z_card", "hour_dev_card", "hours_since_last_card",
             ["card_tx_1h", "card_tx_24h"]),
    "device": ("amt_z_device", "hour_dev_device", "hours_since_last_device",
               ["dev_tx_1h", "dev_tx_24h"]),
}

_WINDOW_UNIT_S = {"h": 3600, "d": 86_400}


def _window_seconds(window_str: str | None) -> int:
    if not window_str:
        return 0
    token = window_str.split("-")[1].split(",")[0].strip().lower()
    unit = token[-1]
    return int(token[:-1]) * _WINDOW_UNIT_S[unit]


_MAX_WINDOW_S = max((_window_seconds(s.window)
                     for s in FEATURE_REGISTRY), default=0)
_PRUNE_S = _MAX_WINDOW_S + 3600


class CausalFeatureEngine:
    """Single-pass engine; feed rows in ascending timestamp order."""

    def __init__(self, min_amount_history: int = 2):
        self.min_amount_history = min_amount_history
        self.entity_ts: dict[tuple[str, str], list[int]] = {}
        self.welford: dict[tuple[str, str], _Welford] = {}
        self.hours: dict[tuple[str, str], _CircularHour] = {}
        self.last_ts: dict[tuple[str, str], int] = {}
        self.pair_ts: dict[tuple, list[int]] = {}
        self.partner_ts: dict[tuple, dict[tuple, list[int]]] = {}

    # -- read path (uses strictly-prior state) --------------------------
    def _entity_features(self, role: str, etype: str, key, t: int,
                         amount, theta: float,
                         out: dict) -> None:
        z_col, hour_col, rec_col, vel_cols = _ENTITY_OUTPUTS[role]
        if key is None:
            out[z_col] = out[hour_col] = out[rec_col] = np.nan
            out[vel_cols[0]] = out[vel_cols[1]] = np.nan
            return
        ek = (etype, key)
        wl = self.welford.get(ek)
        out[z_col] = (wl.z(float(amount), self.min_amount_history)
                      if (wl is not None and amount is not None) else np.nan)
        hd = self.hours.get(ek)
        out[hour_col] = hd.distance(theta) if hd is not None else np.nan
        lt = self.last_ts.get(ek)
        out[rec_col] = ((t - lt) / 3600.0) if lt is not None else np.nan
        ts_list = self.entity_ts.get(ek)
        if ts_list:
            base = bisect_left(ts_list, t)
            out[vel_cols[0]] = float(base - bisect_left(ts_list, t - 3600))
            out[vel_cols[1]] = float(base - bisect_left(ts_list, t - 86_400))
        else:
            out[vel_cols[0]] = 0.0
            out[vel_cols[1]] = 0.0

    def _count_distinct(self, subject: tuple[str, str],
                        partner_type: str, t: int,
                        window_s: int) -> float:
        inner = self.partner_ts.get(subject)
        if not inner:
            return np.nan
        lo = t - window_s
        cnt = 0
        for pk, ts_list in inner.items():
            if pk[0] != partner_type:
                continue
            if bisect_left(ts_list, t) > bisect_left(ts_list, lo):
                cnt += 1
        return float(cnt)

    @staticmethod
    def _absorb_partner(subject: tuple[str, str], partner: tuple[str, str],
                        t: int, store: dict) -> None:
        inner = store.setdefault(subject, {})
        lst = inner.setdefault(partner, [])
        lst.append(t)
        cutoff = t - _PRUNE_S
        while lst and lst[0] < cutoff:
            lst.pop(0)

    # -- main ------------------------------------------------------------
    def process_row(self, t: int, amount,
                    entities: dict[str, str | None]) -> dict:
        """All registry features from strictly-prior state; then absorb."""
        out: dict = {}
        theta = ((int(t) % 86_400) // 3600) * (_TWO_PI / 24.0)

        ckey = _clean(entities.get("card"))
        dkey = _clean(entities.get("device"))
        akey = _clean(entities.get("address"))

        self._entity_features("card", "CARD", ckey, t, amount, theta, out)
        self._entity_features("device", "DEVICE", dkey, t, amount, theta, out)

        if ckey is not None and dkey is not None:
            n_before = self._pair_n_before(("DEVICE", dkey, "CARD", ckey), t)
            out["is_new_device_card_pair"] = 1.0 if n_before == 0 else 0.0
            out["log_pair_count_device_card"] = float(np.log1p(n_before))
            out["device_distinct_cards_24h"] = self._count_distinct(
                ("DEVICE", dkey), "CARD", t, 86_400)
            out["card_distinct_devices_24h"] = self._count_distinct(
                ("CARD", ckey), "DEVICE", t, 86_400)
        else:
            for col in ("is_new_device_card_pair",
                        "log_pair_count_device_card",
                        "device_distinct_cards_24h",
                        "card_distinct_devices_24h"):
                out[col] = np.nan

        if ckey is not None and akey is not None:
            n_before = self._pair_n_before(("ADDRESS", akey, "CARD", ckey), t)
            out["is_new_addr_card_pair"] = 1.0 if n_before == 0 else 0.0
            out["addr_distinct_cards_7d"] = self._count_distinct(
                ("ADDRESS", akey), "CARD", t, 604_800)
        else:
            out["is_new_addr_card_pair"] = np.nan
            out["addr_distinct_cards_7d"] = np.nan

        # ---- absorb AFTER computing (strict causality) ------------------
        for role, etype, key in (("card", "CARD", ckey),
                                 ("device", "DEVICE", dkey)):
            if key is None:
                continue
            ek = (etype, key)
            self.entity_ts.setdefault(ek, []).append(t)
            if amount is not None:
                self.welford.setdefault(ek, _Welford()).absorb(float(amount))
            self.hours.setdefault(ek, _CircularHour()).absorb(theta)
            self.last_ts[ek] = t

        if ckey is not None and dkey is not None:
            self.pair_ts.setdefault(("DEVICE", dkey, "CARD", ckey),
                                    []).append(t)
            self._absorb_partner(("DEVICE", dkey), ("CARD", ckey), t,
                                 self.partner_ts)
            self._absorb_partner(("CARD", ckey), ("DEVICE", dkey), t,
                                 self.partner_ts)
        if ckey is not None and akey is not None:
            self.pair_ts.setdefault(("ADDRESS", akey, "CARD", ckey),
                                    []).append(t)
            self._absorb_partner(("ADDRESS", akey), ("CARD", ckey), t,
                                 self.partner_ts)
        return out

    def _pair_n_before(self, pk: tuple, t: int) -> int:
        """Strictly-prior co-occurrence count (exact ties never count)."""
        lst = self.pair_ts.get(pk)
        return bisect_left(lst, t) if lst else 0


def build_relational_features(df: pd.DataFrame,
                              cols: RelationalInputColumns | None = None,
                              min_amount_history: int = 2,
                             ) -> pd.DataFrame:
    """Deterministic relational feature frame aligned to df's rows.

    Stable sort by timestamp: exact ties keep original row order and are
    never counted as prior.
    """
    cols = cols or RelationalInputColumns()
    engine = CausalFeatureEngine(min_amount_history=min_amount_history)
    n = len(df)
    order = np.argsort(df[cols.ts].to_numpy(), kind="mergesort")
    ts_arr = df[cols.ts].to_numpy()
    amt_arr = (df[cols.amount].to_numpy(dtype="float64")
               if cols.amount in df.columns else np.full(n, np.nan))

    def entity_at(src_i: int, cname: str):
        if cname not in df.columns:
            return None
        return _clean(df[cname].iloc[src_i])

    records: list = [None] * n
    for _, src_i in enumerate(order):
        rec = engine.process_row(
            int(ts_arr[src_i]),
            (float(amt_arr[src_i]) if not np.isnan(amt_arr[src_i]) else None),
            {
                "card": entity_at(src_i, cols.card),
                "device": entity_at(src_i, cols.device),
                "address": entity_at(src_i, cols.address),
            })
        records[src_i] = rec

    missing = [i for i, r in enumerate(records) if r is None]
    assert not missing, f"rows never processed: {missing[:5]}"
    return pd.DataFrame(records, index=df.index,
                        columns=FEATURE_NAMES).astype("float32")
