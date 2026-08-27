# Build the modeling table
# Selection rule (fixed a priori):
# - universe = inner join of train_transaction x train_identity (144,233 rows - every transaction that has identity enrichment);
# - graph features accumulate over the FULL 590,540-row stream so history extends beyond the modeling window;
# - rows sorted chronologically by TransactionDT; split thresholds come from reports/temporal_analysis.json (70/15/15 quantiles of the full data).
# Output: data/processed/experiment_base.parquet (cached; never re-derived).

import json
import sys

import pandas as pd

sys.path.insert(0, ".")
from src.config import DATA_PROC, IDN_PARQUET, REPORTS, TXN_PARQUET
from src.features.graph_features import build_graph_features
from src.graph.schema import clean_device_info
from src.utils import log_resources

with log_resources("load full transaction parquet"):
    txn = pd.read_parquet(TXN_PARQUET)

with log_resources("load identity + clean device"):
    idn = pd.read_parquet(IDN_PARQUET)
    idn["device_id"] = clean_device_info(idn["DeviceInfo"])
    n_dev_before = int(idn["DeviceInfo"].notna().sum())
    n_dev_after = int(idn["device_id"].notna().sum())

with log_resources("merge txn+identity"):
    merged = txn.merge(
        idn[["TransactionID", "device_id", "DeviceType"] +
            [f"id_{i:02d}" for i in range(1, 39)]],
        on="TransactionID", how="inner")
    print("merged:", merged.shape)

with log_resources("causal graph features"):
    gfeats = build_graph_features(txn, merged)

merged["hour"] = ((merged["TransactionDT"] % 86400) // 3600).astype("int8")
merged["dow"] = ((merged["TransactionDT"] // 86400) % 7).astype("int8")

out = pd.concat([merged.reset_index(drop=True),
                 gfeats.reset_index(drop=True)], axis=1)
out = out.drop(columns=["DeviceInfo"], errors="ignore")
assert len(out) == len(merged) == len(gfeats)

gf_cols = [c for c in gfeats.columns]
print(f"\ngraph features ({len(gf_cols)}):")
print(json.dumps(gf_cols, indent=1))
print("\nsanity: card_tx_prior monotonicity spot-check")
chk = out.sort_values(["card1", "TransactionDT"]).groupby("card1")[
    "card_tx_prior"].apply(lambda s: s.iloc[0] <= s.iloc[-1])
print("ok for %.1f%% of cards" % (100 * chk.mean()))

meta = {
    "rows": len(out),
    "fraud_rate_pct": round(float(out["isFraud"].mean() * 100), 3),
    "graph_feature_cols": gf_cols,
    "device_rows_raw": n_dev_before,
    "device_rows_after_generic_cleaning": n_dev_after,
}
with open(REPORTS / "experiment_base_meta.json", "w") as f:
    json.dump(meta, f, indent=2)

with log_resources("write experiment_base.parquet"):
    out.to_parquet(DATA_PROC / "experiment_base.parquet", index=False)
print("saved data/processed/experiment_base.parquet",
      out.shape, f"{(DATA_PROC / 'experiment_base.parquet').stat().st_size/1e6:.0f} MB")
