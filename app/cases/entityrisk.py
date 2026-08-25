# Delayed EntityRisk — deterministic point-in-time aggregate of eligible labels
# NOT a model. NOT a predictive feature. Investigation context only; never wired into the frozen XGBoost pipeline.

# Point-in-time rule (delayed-label discipline): a label is eligible at query time T iff  arrival_at <= T - MIN_LABEL_LAG (inclusive boundary; one unit later is not eligible).
# Clock semantics: `as_of_ts` lives on the IEEE-CIS TransactionDT clock (seconds since the 2017-12-01 anchor, per reports/temporal_analysis.json), while `labels.arrival_at` is a wall-clock TIMESTAMP. All comparisons convert the TransactionDT boundary to real UTC via TS_ANCHOR_UNIX_S.

from dataclasses import dataclass
from datetime import UTC, datetime

import duckdb

# 2017-12-01T00:00:00Z — the dataset anchor (reports/temporal_analysis.json)
TS_ANCHOR_UNIX_S = 1512086400

MIN_OBSERVATIONS = 1


@dataclass(frozen=True)
class EntityRiskResult:
    entity_type: str
    entity_key: str
    as_of_ts: int | None           # seconds on the TransactionDT clock
    min_label_lag_days: int
    eligible_boundary: str | None  # ISO UTC instant labels must arrive before
    entity_fraud_count: int
    entity_total_labeled_count: int
    fraud_rate: float | None       # None when below MIN_OBSERVATIONS
    note: str = ""


def _boundary_datetime(as_of_ts: int, min_label_lag_days: int) -> datetime:
    # Real-UTC instant that arrival_at must be <= for eligibility
    # Returns a NAIVE UTC datetime to match labels.arrival_at storage (naive TIMESTAMP written from datetime.now(UTC).replace(tzinfo=None)).
    
    lag_s = int(min_label_lag_days) * 86400
    unix_s = TS_ANCHOR_UNIX_S + int(as_of_ts) - lag_s
    return datetime.fromtimestamp(unix_s, tz=UTC).replace(tzinfo=None)


def _iso(dt: datetime) -> str:
    return dt.replace(tzinfo=UTC).isoformat()


def label_is_eligible(arrival_epoch_s: int, query_ts: int,
                      min_label_lag_days: int) -> bool:
    # Pure boundary predicate used by tests: inclusive at exactly T - LAG. All arguments live on the TransactionDT clock (anchor-based seconds).
    return arrival_epoch_s <= query_ts - int(min_label_lag_days) * 86400


def compute_entity_risk(conn: duckdb.DuckDBPyConnection, entity_type: str,
                        entity_key: str, as_of_ts: int | None,
                        min_label_lag_days: int) -> EntityRiskResult:
    # Deterministic aggregation of eligible labels for one entity
    if as_of_ts is None:
        return EntityRiskResult(entity_type, entity_key, None,
                                min_label_lag_days, None, 0, 0, None,
                                "as_of_ts required")
    txn_rows = conn.execute(
        "SELECT transaction_id FROM graph_links WHERE entity_type=?"
        " AND entity_key=?", [entity_type, entity_key]).fetchall()
    txn_ids = sorted({int(r[0]) for r in txn_rows})
    if not txn_ids:
        return EntityRiskResult(entity_type, entity_key, int(as_of_ts),
                                min_label_lag_days, None, 0, 0, None,
                                "no linked transactions")
    boundary = _boundary_datetime(as_of_ts, min_label_lag_days)
    placeholders = ",".join(["?"] * len(txn_ids))
    rows = conn.execute(
        f"SELECT value FROM labels WHERE txn_id IN ({placeholders})"
        " AND value IN (0, 1)"
        " AND arrival_at IS NOT NULL"
        " AND arrival_at <= ?",
        [*txn_ids, boundary]).fetchall()
    total = len(rows)
    fraud = sum(1 for (v,) in rows if int(v) == 1)
    rate = (fraud / total) if total >= MIN_OBSERVATIONS else None
    return EntityRiskResult(
        entity_type=entity_type, entity_key=entity_key, as_of_ts=int(as_of_ts),
        min_label_lag_days=int(min_label_lag_days),
        eligible_boundary=_iso(boundary),
        entity_fraud_count=fraud, entity_total_labeled_count=total,
        fraud_rate=rate)
