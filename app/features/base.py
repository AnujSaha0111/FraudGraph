# Base feature pipeline — productized port of the validated research baseline matrix (src/models/baselines.build_matrix).

# Semantics are intentionally IDENTICAL to the research implementation so the reproduction experiment can assert matrix-level equality:
# - log1p(amount);
# - fixed numeric block;
# - frequency encodings fitted on TRAIN rows only, unseen -> -1;
# - M1-M9 mapped T/F -> 1/0.

# No model code lives here.

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

NUMERIC_BASE = ["dist1", "dist2", "addr1", "addr2",
                *[f"C{i}" for i in range(1, 15)],
                *[f"D{i}" for i in range(1, 16)],
                *[f"V{i}" for i in range(1, 340)],
                *[f"id_{i:02d}" for i in range(1, 12)],
                "hour", "dow", "card2", "card3", "card5"]
FREQ_CATS = ["ProductCD", "card4", "card6", "card1", "P_emaildomain",
             "R_emaildomain", "DeviceType",
             *[f"M{i}" for i in range(1, 10)],
             *[f"id_{i:02d}" for i in range(12, 39)]]
FEATURE_NAMES = ["logTransactionAmt", *NUMERIC_BASE]


@dataclass
class BaseFeaturePipeline:
    freq_maps: dict[str, dict] = field(default_factory=dict)

    def fit(self, train_df: pd.DataFrame) -> "BaseFeaturePipeline":
        for c in FREQ_CATS:
            if c.startswith("M"):
                continue
            vc = train_df[c].value_counts(normalize=True)
            self.freq_maps[c] = {str(k): float(v) for k, v in vc.items()}
        return self

    def transform(self, df: pd.DataFrame) -> np.ndarray:
        parts = [
            np.log1p(df["TransactionAmt"].to_numpy(dtype="float64"))
            .astype("float32")]
        parts.append(
            df[NUMERIC_BASE].astype("float32").to_numpy())
        for c in FREQ_CATS:
            s = df[c]
            if c.startswith("M"):
                parts.append(s.map({"T": 1.0, "F": 0.0})
                             .astype("float32").to_numpy())
                continue
            fmap = self.freq_maps.get(c, {})
            fe = s.astype(object).map(
                lambda v, _f=fmap: _f.get(str(v), -1.0))
            parts.append(fe.astype("float32").to_numpy())
        return np.column_stack(parts)

    def fit_transform(self, train_df: pd.DataFrame,
                      full_df: pd.DataFrame) -> np.ndarray:
        return self.fit(train_df).transform(full_df)
