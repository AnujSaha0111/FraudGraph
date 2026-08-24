import pandas as pd
import pytest

from app.data.splits import chronological_split, quantile_boundaries


def make_df(ts_values):
    return pd.DataFrame({"TransactionDT": ts_values,
                         "isFraud": [0] * len(ts_values)})


def test_chronological_split_partitions_and_ordering():
    df = make_df([1, 2, 3, 10, 11, 20, 21, 30])
    res = chronological_split(df, train_end=10, valid_end=20)

    assert list(df.TransactionDT[res.train]) == [1, 2, 3]
    assert list(df.TransactionDT[res.valid]) == [10, 11]
    assert list(df.TransactionDT[res.test]) == [20, 21, 30]

    # Ordering assertions hold by construction
    assert df.TransactionDT[res.train].max() < df.TransactionDT[res.valid].min()
    assert df.TransactionDT[res.valid].max() < df.TransactionDT[res.test].min()


def test_split_is_deterministic():
    df = make_df(list(range(100)))
    a = chronological_split(df, 60, 80)
    b = chronological_split(df, 60, 80)
    assert (a.train == b.train).all()
    assert (a.valid == b.valid).all()
    assert (a.test == b.test).all()


def test_invalid_boundaries_rejected():
    with pytest.raises(AssertionError):
        chronological_split(make_df(range(10)), train_end=50, valid_end=40)


def test_no_random_splitting_api_exists():
    from app.data import splits
    forbidden = {"train_test_split", "stratified"}
    names = {n for n in dir(splits) if not n.startswith("_")}
    assert not (forbidden & names)


def test_quantile_boundaries_ordered():
    t1, t2 = quantile_boundaries(pd.Series(range(1000)), (0.7, 0.85))
    assert t1 < t2
    assert t1 == pytest.approx(699.3, abs=1.0)
