# Audit IEEE-CIS train_transaction.csv / train_identity.csv
# Single chunked pass per file:
# - collects row counts, missingness, target prevalence, TransactionDT range, duplicate TransactionIDs, nunique for candidate entity columns
# - writes a downcast parquet cache (data/processed/) so later steps never re-read the 683 MB CSV.
# Raw CSVs are never modified.

import json
import sys

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, ".")
from src.config import IDN_PARQUET, IEEE_IDN_CSV, IEEE_TXN_CSV, REPORTS, TXN_PARQUET
from src.utils import log_resources, peak_rss_gb, system_ram_gb

CHUNK = 60_000

TXN_DTYPES = {
    "TransactionID": "int32", "isFraud": "int8", "TransactionDT": "int32",
    "TransactionAmt": "float32",
}
for c in ["card2", "card3", "card5", "addr1", "addr2", "dist1", "dist2"]:
    TXN_DTYPES[c] = "float32"
TXN_DTYPES["card1"] = "int32"
for c in [f"C{i}" for i in range(1, 15)] + [f"D{i}" for i in range(1, 16)] \
        + [f"V{i}" for i in range(1, 340)]:
    TXN_DTYPES[c] = "float32"
for c in ["ProductCD", "card4", "card6", "P_emaildomain", "R_emaildomain"] \
        + [f"M{i}" for i in range(1, 10)]:
    TXN_DTYPES[c] = "string"

IDN_DTYPES = {"TransactionID": "int32"}
for i in range(1, 12):
    IDN_DTYPES[f"id_{i:02d}"] = "float32"
for i in range(12, 39):
    IDN_DTYPES[f"id_{i:02d}"] = "string"
IDN_DTYPES["DeviceType"] = "string"
IDN_DTYPES["DeviceInfo"] = "string"

# entity-like columns whose cardinality we track exactly across chunks
CAND_TXN = ["ProductCD", "card1", "card2", "card3", "card4", "card5", "card6",
            "addr1", "addr2", "P_emaildomain", "R_emaildomain"]
CAND_IDN = ["DeviceType", "DeviceInfo", "id_30", "id_31", "id_33"]


def audit_csv(path, dtype_map, cand_cols, out_parquet):
    stats = {
        "file": str(path), "size_mb": round(path.stat().st_size / 1e6, 1),
        "rows": 0, "cols": None,
        "missing": {}, "nunique": {c: set() for c in cand_cols},
        "dup_txn_ids": None,
    }
    txn_ids = []
    writer = None
    first_min, first_max = np.inf, -np.inf
    extra = {}
    if "isFraud" in dtype_map:
        fraud_sum = 0
        dt_min, dt_max = np.inf, -np.inf

    reader = pd.read_csv(path, dtype=dtype_map, chunksize=CHUNK)
    for i, chunk in enumerate(reader):
        if stats["cols"] is None:
            stats["cols"] = int(chunk.shape[1])
        stats["rows"] += len(chunk)
        m = chunk.isna().sum()
        for col in m.index:
            stats["missing"][col] = stats["missing"].get(col, 0) + int(m[col])
        for c in cand_cols:
            if c in chunk:
                stats["nunique"][c].update(chunk[c].dropna().unique().tolist())
        if "isFraud" in chunk:
            fraud_sum += int(chunk["isFraud"].sum())
            dt_min = min(dt_min, int(chunk["TransactionDT"].min()))
            dt_max = max(dt_max, int(chunk["TransactionDT"].max()))
        txn_ids.append(chunk["TransactionID"])

        table = pa.Table.from_pandas(chunk, preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(out_parquet, table.schema,
                                      compression="snappy")
        writer.write_table(table)
        del chunk, table, m
        if i % 3 == 0:
            print(f"  chunk {i}: rows={stats['rows']}", flush=True)
    if writer is not None:
        writer.close()

    ids = pd.concat(txn_ids, ignore_index=True)
    stats["dup_txn_ids"] = int(ids.duplicated().sum())
    del ids, txn_ids

    stats["nunique"] = {c: len(v) for c, v in stats["nunique"].items()}
    stats["missing_pct"] = {k: round(100.0 * v / stats["rows"], 2)
                            for k, v in stats["missing"].items()}
    stats["peak_rss_gb"] = round(peak_rss_gb(), 3)
    if "isFraud" in dtype_map:
        stats["fraud_count"] = fraud_sum
        stats["fraud_rate_pct"] = round(100.0 * fraud_sum / stats["rows"], 4)
        stats["transactiondt_min"] = int(dt_min)
        stats["transactiondt_max"] = int(dt_max)
        stats["span_days_approx"] = round((dt_max - dt_min) / 86400.0, 2)
    return stats


def main():
    REPORTS.mkdir(exist_ok=True, parents=True)
    print("system RAM:", system_ram_gb())

    with log_resources("audit+convert train_transaction"):
        tx_stats = audit_csv(IEEE_TXN_CSV, TXN_DTYPES, CAND_TXN, TXN_PARQUET)
    print(json.dumps({k: v for k, v in tx_stats.items()
                      if k not in ("missing",)}, indent=2)[:2000])

    with log_resources("audit+convert train_identity"):
        id_stats = audit_csv(IEEE_IDN_CSV, IDN_DTYPES, CAND_IDN, IDN_PARQUET)

    out = {"train_transaction": tx_stats, "train_identity": id_stats}
    with open(REPORTS / "ieee_audit.json", "w") as f:
        json.dump(out, f, indent=2, default=str)
    print("saved reports/ieee_audit.json")


if __name__ == "__main__":
    main()
