"""DuckDB storage layer.

Scope: connect, idempotent schema initialization, readiness check.
Schemas are plain SQL DDL so a later Postgres migration
stays confined to this module.
"""
from pathlib import Path

import duckdb

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS transactions(
  txn_id BIGINT PRIMARY KEY,
  ts BIGINT NOT NULL,
  amount DOUBLE,
  score DOUBLE,
  is_fraud TINYINT
);
CREATE TABLE IF NOT EXISTS links(
  entity_type VARCHAR NOT NULL,
  entity_key VARCHAR NOT NULL,
  txn_id BIGINT NOT NULL,
  ts BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence(
  evidence_id VARCHAR PRIMARY KEY,
  txn_id BIGINT NOT NULL,
  evidence_type VARCHAR NOT NULL,
  payload VARCHAR,
  evidence_hash VARCHAR,
  generated_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS cases(
  case_id BIGINT PRIMARY KEY,
  subject_txn_id BIGINT NOT NULL,
  status VARCHAR NOT NULL,
  opened_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS decisions(
  decision_id BIGINT PRIMARY KEY,
  case_id BIGINT NOT NULL,
  reviewer VARCHAR,
  decision VARCHAR NOT NULL,
  decided_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS labels(
  label_id BIGINT PRIMARY KEY,
  txn_id BIGINT NOT NULL,
  source VARCHAR,
  value TINYINT,
  effective_at TIMESTAMP,
  arrival_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS risk_predictions(
  transaction_id BIGINT,
  model_version VARCHAR,
  risk_score DOUBLE,
  risk_band VARCHAR,
  scored_at TIMESTAMP,
  PRIMARY KEY (transaction_id, model_version)
);
CREATE TABLE IF NOT EXISTS graph_links(
  entity_type VARCHAR,
  entity_key VARCHAR,
  transaction_id BIGINT,
  ts BIGINT
);
CREATE TABLE IF NOT EXISTS case_history(
  history_id BIGINT PRIMARY KEY,
  case_id BIGINT NOT NULL,
  actor VARCHAR,
  action VARCHAR NOT NULL,
  prev_status VARCHAR,
  new_status VARCHAR,
  details VARCHAR,
  created_at TIMESTAMP
);
"""

# Columns added after the initial schema (idempotent migration for existing stores).
_MIGRATIONS = [
    "ALTER TABLE cases ADD COLUMN IF NOT EXISTS title VARCHAR",
    "ALTER TABLE cases ADD COLUMN IF NOT EXISTS actor VARCHAR",
    "ALTER TABLE cases ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP",
    "ALTER TABLE decisions ADD COLUMN IF NOT EXISTS transaction_id BIGINT",
    "ALTER TABLE decisions ADD COLUMN IF NOT EXISTS notes VARCHAR",
    "ALTER TABLE decisions ADD COLUMN IF NOT EXISTS evidence_ids VARCHAR",
    "ALTER TABLE decisions ADD COLUMN IF NOT EXISTS request_id VARCHAR",
    "ALTER TABLE labels ADD COLUMN IF NOT EXISTS case_id BIGINT",
    "ALTER TABLE labels ADD COLUMN IF NOT EXISTS decision_id BIGINT",
    "ALTER TABLE labels ADD COLUMN IF NOT EXISTS created_at TIMESTAMP",
]


def connect(db_path: Path | str) -> duckdb.DuckDBPyConnection:
    path = Path(db_path)
    if path.parent and str(path.parent):
        path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path))


def init_db(db_path: Path | str) -> duckdb.DuckDBPyConnection:
    conn = connect(db_path)
    conn.execute(SCHEMA_SQL)
    migrate(conn)
    return conn


def migrate(conn: duckdb.DuckDBPyConnection) -> None:
    """Idempotent column/table additions for stores created by older versions."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS case_history(
          history_id BIGINT PRIMARY KEY,
          case_id BIGINT NOT NULL,
          actor VARCHAR,
          action VARCHAR NOT NULL,
          prev_status VARCHAR,
          new_status VARCHAR,
          details VARCHAR,
          created_at TIMESTAMP
        );
    """)
    for stmt in _MIGRATIONS:
        try:
            conn.execute(stmt)
        except duckdb.Error:
            # Column already exists on engines without IF NOT EXISTS support.
            pass


def readiness(conn: duckdb.DuckDBPyConnection) -> bool:
    try:
        conn.execute("SELECT 1").fetchone()
        return True
    except Exception:  # noqa: BLE001 - readiness probe must not raise
        return False


def required_tables() -> set[str]:
    return {"transactions", "links", "evidence", "cases", "decisions",
            "labels", "risk_predictions", "graph_links"}


def existing_tables(conn: duckdb.DuckDBPyConnection) -> set[str]:
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables"
    ).fetchall()
    return {r[0] for r in rows}
