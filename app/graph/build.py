# Graph link building — deterministic, reproducible from source transactions
import time
from pathlib import Path

import pandas as pd

from src.graph.schema import clean_device_info

# Canonical entity definitions for IEEE-CIS
LINK_SCHEMA = ["entity_type", "entity_key", "transaction_id", "ts"]

def build_graph_links_df(df: pd.DataFrame) -> pd.DataFrame:
    # Build link rows from experiment_base-like DataFrame
    # Expects columns: TransactionID, TransactionDT, card1, addr1, device_id (or DeviceInfo cleaned)
    # Returns DataFrame with columns entity_type, entity_key, transaction_id, ts sorted deterministically
    
    rows = []
    # Card
    for _, r in df[["TransactionID", "TransactionDT", "card1"]].iterrows():
        if pd.notna(r["card1"]):
            rows.append(("CARD", str(int(r["card1"])), int(r["TransactionID"]), int(r["TransactionDT"])))
    # Address
    if "addr1" in df.columns:
        for _, r in df[["TransactionID", "TransactionDT", "addr1"]].iterrows():
            if pd.notna(r["addr1"]):
                # keep as int if numeric else str
                try:
                    key = str(int(r["addr1"]))
                except (ValueError, TypeError):
                    key = str(r["addr1"])
                rows.append(("ADDRESS", key, int(r["TransactionID"]), int(r["TransactionDT"])))
    # Device - df may have device_id already cleaned or DeviceInfo raw
    dev_col = None
    if "device_id" in df.columns:
        dev_col = "device_id"
    elif "device_key" in df.columns:
        dev_col = "device_key"
    if dev_col:
        for _, r in df[["TransactionID", "TransactionDT", dev_col]].iterrows():
            v = r[dev_col]
            if pd.notna(v) and str(v).strip().lower() not in ("", "nan", "none"):
                rows.append(("DEVICE", str(v), int(r["TransactionID"]), int(r["TransactionDT"])))
    # Sort deterministically: ts, transaction_id, entity_type, entity_key (stable)
    links = pd.DataFrame(rows, columns=LINK_SCHEMA)
    links = links.sort_values(["ts", "transaction_id", "entity_type", "entity_key"], kind="mergesort").reset_index(drop=True)
    return links

def build_graph_links(source_parquet: Path, output_parquet: Path, duckdb_path: Path | None = None) -> dict:
    """Read source, build links, persist to Parquet and optionally DuckDB."""
    import duckdb
    t0 = time.perf_counter()
    # Prefer experiment_base if available
    if source_parquet.name == "experiment_base.parquet":
        df = pd.read_parquet(source_parquet, columns=["TransactionID", "TransactionDT", "card1", "addr1", "device_id"])
    else:
        # raw transaction + identity join
        txn = pd.read_parquet(source_parquet)
        # try to find device column
        df = txn
        if "DeviceInfo" in df.columns:
            df = df.copy()
            df["device_id"] = clean_device_info(df["DeviceInfo"])
    links = build_graph_links_df(df)
    # persist parquet
    output_parquet.parent.mkdir(parents=True, exist_ok=True)
    links.to_parquet(output_parquet, index=False)
    dt = time.perf_counter() - t0
    result = {"rows": len(links), "entities": links["entity_key"].nunique(), "build_seconds": round(dt, 3), "output": str(output_parquet)}
    if duckdb_path:
        con = duckdb.connect(str(duckdb_path))
        con.execute("CREATE TABLE IF NOT EXISTS graph_links (entity_type VARCHAR, entity_key VARCHAR, transaction_id BIGINT, ts BIGINT)")
        con.execute("DELETE FROM graph_links")
        con.register("links_df", links)
        con.execute("INSERT INTO graph_links SELECT * FROM links_df")
        con.unregister("links_df")
        con.close()
        result["duckdb"] = str(duckdb_path)
    return result
