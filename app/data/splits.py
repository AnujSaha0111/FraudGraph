# Chronological splitting (hard rules).
# Random/stratified splits are intentionally not provided. Boundaries come from reports/temporal_analysis.json (IEEE-CIS) or explicit quantiles for other datasets.

from collections import namedtuple

import numpy as np
import pandas as pd

SplitResult = namedtuple("SplitResult",
                         ["train", "valid", "test",
                          "train_end", "valid_end"])


def quantile_boundaries(ts: pd.Series,
                        fractions: tuple[float, float] = (0.70, 0.85)
                        ) -> tuple[float, float]:
    t1 = float(np.quantile(ts.to_numpy(), fractions[0]))
    t2 = float(np.quantile(ts.to_numpy(), fractions[1]))
    assert t1 < t2
    return t1, t2


def chronological_split(df: pd.DataFrame,
                        train_end: float,
                        valid_end: float,
                        ts_col: str = "TransactionDT") -> SplitResult:
    """Deterministic chronological 3-way split.

    train :  ts <  train_end
    valid :  train_end <= ts < valid_end
    test  :  ts >= valid_end
    """
    assert train_end < valid_end, "train_end must precede valid_end"
    ts = df[ts_col].to_numpy()
    train = ts < train_end
    valid = (ts >= train_end) & (ts < valid_end)
    test = ts >= valid_end

    if train.any() and valid.any():
        assert ts[train].max() < ts[valid].min(), \
            "temporal leakage: train overlaps validation"
    if valid.any() and test.any():
        assert ts[valid].max() < ts[test].min(), \
            "temporal leakage: validation overlaps test"
    return SplitResult(train, valid, test, float(train_end), float(valid_end))
