# Temporal structure of IEEE-CIS TransactionDT + split definition.
# Outputs:
# - reports/temporal_analysis.json
# - console summary
# Defines chronological 70/15/15 boundaries used by ALL later experiments.

import json
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from src.config import REPORTS, TRAIN_FRACTION, TXN_PARQUET, VALID_FRACTION

# Public dataset convention: TransactionDT is seconds elapsed from a reference;
# day boundary = multiples of 86400. Anchor date chosen as 2017-12-01 (Mon).
ANCHOR = pd.Timestamp("2017-12-01")

df = pd.read_parquet(TXN_PARQUET, columns=["TransactionID", "TransactionDT",
                                           "isFraud"])
df["day"] = df["TransactionDT"] // 86400
per_day = df.groupby("day").agg(n=("isFraud", "size"),
                                frauds=("isFraud", "sum"))
per_day["rate"] = per_day["frauds"] / per_day["n"]
per_day["dow"] = [(int(d) % 7) for d in per_day.index]

print("days:", len(per_day), "| range:",
      ANCHOR + pd.Timedelta(days=int(per_day.index.min())), "->",
      ANCHOR + pd.Timedelta(days=int(per_day.index.max())))
print("tx/day mean=%.0f std=%.0f min=%d max=%d"
      % (per_day.n.mean(), per_day.n.std(), per_day.n.min(), per_day.n.max()))
print("overall fraud rate %.3f%%" % (100 * df.isFraud.mean()))
print("\nfirst 14 days:")
print(per_day.head(14).to_string())

# hour-of-day pattern
df["hour"] = (df["TransactionDT"] % 86400) // 3600
hr = df.groupby("hour").agg(n=("isFraud", "size"), f=("isFraud", "sum"))
hr["rate"] = hr.f / hr.n
print("\nhourly fraud rate: min=%.2f%%@h%d max=%.2f%%@h%d"
      % (100 * hr.rate.min(), int(hr.rate.idxmin()),
         100 * hr.rate.max(), int(hr.rate.idxmax())))

# ---- chronological split -------------------------------------------------
q_train = TRAIN_FRACTION
q_valid = TRAIN_FRACTION + VALID_FRACTION
t_train = float(np.quantile(df["TransactionDT"], q_train))
t_valid = float(np.quantile(df["TransactionDT"], q_valid))
n_tr = int((df["TransactionDT"] < t_train).sum())
n_va = int(((df["TransactionDT"] >= t_train) & (df["TransactionDT"] < t_valid)).sum())
n_te = int((df["TransactionDT"] >= t_valid).sum())
r_tr = 100 * df.loc[df.TransactionDT < t_train, "isFraud"].mean()
r_va = 100 * df.loc[(df.TransactionDT >= t_train) & (df.TransactionDT < t_valid), "isFraud"].mean()
r_te = 100 * df.loc[df.TransactionDT >= t_valid, "isFraud"].mean()

out = {
    "anchor": str(ANCHOR),
    "dt_min": int(df.TransactionDT.min()), "dt_max": int(df.TransactionDT.max()),
    "span_days": int(per_day.index.max() - per_day.index.min() + 1),
    "split_dt_train_end": t_train, "split_dt_valid_end": t_valid,
    "rows": {"train": n_tr, "valid": n_va, "test": n_te},
    "fraud_rate_pct": {"train": round(float(r_tr), 3),
                       "valid": round(float(r_va), 3),
                       "test": round(float(r_te), 3)},
    "daily_counts_mean": float(per_day.n.mean()),
}
with open(REPORTS / "temporal_analysis.json", "w") as f:
    json.dump(out, f, indent=2)
per_day.to_csv(REPORTS / "temporal_daily_counts.csv")

print(f"\nsplit @ DT {t_train:.0f} / {t_valid:.0f} "
      f"(day {t_train//86400:.1f} / {t_valid//86400:.1f})")
print(f"train {n_tr} ({r_tr:.2f}% fraud) | valid {n_va} ({r_va:.2f}%) | "
      f"test {n_te} ({r_te:.2f}%)")
