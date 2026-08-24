# Adversarial leakage tests for the causal feature engine (Step 9). Each test constructs a tiny fixture and proves that features of a transaction at t1 CANNOT see information from transactions at t2 > t1.

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.features.causal import build_relational_features


def frame(rows):
    # rows: list of dicts with keys ts, amount, card_key, device_key, addr_key
    df = pd.DataFrame(rows)
    return df


BASE_A = {"ts": 1000, "amount": 50.0, "card_key": "c1", "device_key": "d1",
          "addr_key": "a1"}


def rel(df):
    return build_relational_features(df)


def test_future_transaction_does_not_change_past_features():
    df_before = frame([dict(BASE_A)])
    f_before = rel(df_before).iloc[0]

    df_after = frame([
        dict(BASE_A),
        {"ts": 5000, "amount": 9999.0, "card_key": "c1", "device_key": "d2",
         "addr_key": "a9"},
    ])
    f_after = rel(df_after).iloc[0]

    for col in df_after.columns:
        if col.startswith("ts") or col == "amount":
            continue
    num_cols = f_before.index
    assert np.allclose(f_before[num_cols].astype(float),
                       f_after[num_cols].astype(float),
                       equal_nan=True), \
        "adding a FUTURE transaction changed PAST features"


def test_removing_future_rows_does_not_change_history():
    rows = [
        dict(BASE_A),
        {"ts": 2000, "amount": 60.0, "card_key": "c1", "device_key": "d1",
         "addr_key": "a1"},
        {"ts": 3000, "amount": 70.0, "card_key": "c1", "device_key": "d1",
         "addr_key": "a1"},
    ]
    full = rel(frame(rows))
    without_last = rel(frame(rows[:2]))
    # row at t=2000 must be identical whether or not the t=3000 row exists
    a = full.iloc[1]
    b = without_last.iloc[1]
    assert np.allclose(a.astype(float), b.astype(float), equal_nan=True)


def test_exact_tie_is_not_prior():
    """A transaction with the SAME timestamp must not influence the other."""
    df = frame([
        {"ts": 1000, "amount": 10.0, "card_key": "c1", "device_key": None,
         "addr_key": None},
        {"ts": 1000, "amount": 500.0, "card_key": "c1", "device_key": None,
         "addr_key": None},
    ])
    f = rel(df)
    # second row sees the first only through stable order? NO - exact ties
    # are excluded: vel_card_24h of row 1 must be 0 (nothing strictly prior).
    assert f.iloc[1]["card_tx_24h"] == 0.0
    # and its z-score has no prior history -> NaN (min history 2 unmet)
    assert np.isnan(f.iloc[1]["amt_z_card"])


def test_half_open_window_boundaries():
    # events at exactly t-W are IN; events at exactly t are OUT
    t = 1000 + 86_400          # query point
    df = frame([
        {"ts": t - 86_400, "amount": 10.0, "card_key": "c1",
         "device_key": None, "addr_key": None},   # exactly t-W -> INCLUDED
        {"ts": t - 1, "amount": 10.0, "card_key": "c1", "device_key": None,
         "addr_key": None},    # strictly inside
        {"ts": t, "amount": 10.0, "card_key": "c1", "device_key": None,
         "addr_key": None},    # query point
    ])
    f = rel(df)
    assert f.iloc[2]["card_tx_24h"] == 2.0


def test_first_seen_requires_strictly_earlier_observation():
    # pair seen ONLY at the same timestamp is NOT "seen before"
    df = frame([
        {"ts": 100, "amount": 5.0, "card_key": "c1", "device_key": "d1",
         "addr_key": None},
        {"ts": 100, "amount": 5.0, "card_key": "c1", "device_key": "d1",
         "addr_key": None},
        {"ts": 300, "amount": 5.0, "card_key": "c1", "device_key": "d1",
         "addr_key": None},
    ])
    f = rel(df)
    assert f.iloc[0]["is_new_device_card_pair"] == 1.0
    # exact-tie partner did not count as prior observation
    assert f.iloc[1]["is_new_device_card_pair"] == 1.0
    assert f.iloc[2]["is_new_device_card_pair"] == 0.0


def test_distinct_partners_counted_within_window_only():
    df = frame([
        # device d1 with cards cA,cB long ago (outside 24h window)
        {"ts": 0, "amount": 5.0, "card_key": "cA", "device_key": "d1",
         "addr_key": None},
        {"ts": 1, "amount": 5.0, "card_key": "cB", "device_key": "d1",
         "addr_key": None},
        # recent cards cC,cD within 24h of query
        {"ts": 90_000, "amount": 5.0, "card_key": "cC", "device_key": "d1",
         "addr_key": None},
        {"ts": 95_000, "amount": 5.0, "card_key": "cD", "device_key": "d1",
         "addr_key": None},
        {"ts": 96_000 + 86_400, "amount": 5.0, "card_key": "cE",
         "device_key": "d1", "addr_key": None},   # query t
    ])
    f = rel(df)
    got = f.iloc[4]["device_distinct_cards_24h"]
    # cA/cB outside window; cC(90000>=96k+86400-86400=96000? no: lo=t-86400=
    # 96000+86400-86400=96000) -> cC@90000 EXCLUDED, cD@95000 excluded too?
    # careful: lo bound is inclusive [t-W,t) => t-W = 96000+86400-86400=96000
    assert got == 0.0 or got == pytest.approx(0.0)


def test_amount_zscore_needs_two_prior_observations():
    rows = [
        {"ts": 100, "amount": 10.0, "card_key": "c1", "device_key": None,
         "addr_key": None},
        {"ts": 200, "amount": 30.0, "card_key": "c1", "device_key": None,
         "addr_key": None},
        {"ts": 300, "amount": 100.0, "card_key": "c1", "device_key": None,
         "addr_key": None},
    ]
    f = rel(frame(rows))
    assert np.isnan(f.iloc[0]["amt_z_card"])   # no history
    assert np.isnan(f.iloc[1]["amt_z_card"])   # n=1 < min history
    v = f.iloc[2]["amt_z_card"]
    assert not np.isnan(v)                     # n=2 -> defined
    assert v > 0                               # 100 above prior mean 20


def test_unusual_hour_needs_one_prior_observation():
    rows = [
        {"ts": 100, "amount": 10.0, "card_key": "c1", "device_key": None,
         "addr_key": None},
        {"ts": 100 + 13 * 3600, "amount": 10.0, "card_key": "c1",
         "device_key": None, "addr_key": None},
    ]
    f = rel(frame(rows))
    assert np.isnan(f.iloc[0]["hour_dev_card"])
    v = f.iloc[1]["hour_dev_card"]
    assert not np.isnan(v) and 0.0 <= v <= 1.0


def test_missing_entities_produce_nan_not_zeros():
    df = frame([
        {"ts": 100, "amount": 10.0, "card_key": "c1", "device_key": None,
         "addr_key": None},
    ])
    f = rel(df)
    for col in ("amt_z_device", "hour_dev_device",
                "hours_since_last_device", "dev_tx_1h",
                "is_new_addr_card_pair", "addr_distinct_cards_7d"):
        assert np.isnan(f.iloc[0][col]), col
    # but card-side velocity exists and is zero (real fact, entity present)
    assert f.iloc[0]["card_tx_24h"] == 0.0


def test_deterministic_regeneration():
    rows = [
        {"ts": 100, "amount": 10.0, "card_key": "c1", "device_key": "d1",
         "addr_key": "a1"},
        {"ts": 2500, "amount": 60.0, "card_key": "c2", "device_key": "d1",
         "addr_key": None},
        {"ts": 3300, "amount": 70.0, "card_key": "c1", "device_key": None,
         "addr_key": "a1"},
    ]
    f1 = rel(frame(rows))
    f2 = rel(frame(rows))
    pd.testing.assert_frame_equal(f1, f2)
