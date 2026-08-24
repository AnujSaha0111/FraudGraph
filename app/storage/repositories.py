# Thin storage repositories.
# These are access-layer primitives only — persistence round-trips proven by tests. Business logic (risk scoring, evidence generation, case state machine) lives above this layer.
from typing import Any

import duckdb


def _to_dicts(cur: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


class TransactionRepository:
    def __init__(self, conn: duckdb.DuckDBPyConnection):
        self.conn = conn

    def upsert(self, txn: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO transactions VALUES (?, ?, ?, ?, ?)",
            [txn["txn_id"], txn["ts"], txn.get("amount"), txn.get("score"),
             txn.get("is_fraud")])

    def get_by_id(self, txn_id: int) -> dict[str, Any] | None:
        rows = _to_dicts(self.conn.execute(
            "SELECT * FROM transactions WHERE txn_id = ?", [txn_id]))
        return rows[0] if rows else None

    def top_by_score(self, k: int) -> list[dict[str, Any]]:
        return _to_dicts(self.conn.execute(
            "SELECT * FROM transactions ORDER BY score DESC LIMIT ?", [k]))

    def count(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM transactions").fetchone()[0]


class EvidenceRepository:
    def __init__(self, conn: duckdb.DuckDBPyConnection):
        self.conn = conn

    def add(self, rec: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO evidence VALUES (?, ?, ?, ?, ?, ?)",
            [rec["evidence_id"], rec["txn_id"], rec["evidence_type"],
             rec.get("payload"), rec.get("evidence_hash"),
             rec.get("generated_at")])

    def for_transaction(self, txn_id: int) -> list[dict[str, Any]]:
        return _to_dicts(self.conn.execute(
            "SELECT * FROM evidence WHERE txn_id = ?", [txn_id]))


class CaseRepository:
    def __init__(self, conn: duckdb.DuckDBPyConnection):
        self.conn = conn

    def create(self, case_id: int, subject_txn_id: int, status: str,
               opened_at, title: str | None = None, actor: str | None = None,
               updated_at=None) -> int:
        self.conn.execute(
            "INSERT INTO cases (case_id, subject_txn_id, status, opened_at,"
            " title, actor, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [case_id, subject_txn_id, status, opened_at, title, actor,
             updated_at])
        return case_id

    def get(self, case_id: int) -> dict[str, Any] | None:
        rows = _to_dicts(self.conn.execute(
            "SELECT * FROM cases WHERE case_id = ?", [case_id]))
        return rows[0] if rows else None

    def update_status(self, case_id: int, status: str) -> None:
        self.conn.execute(
            "UPDATE cases SET status = ? WHERE case_id = ?",
            [status, case_id])


class DecisionRepository:
    def __init__(self, conn: duckdb.DuckDBPyConnection):
        self.conn = conn

    def add(self, decision_id: int, case_id: int, reviewer: str,
            decision: str, decided_at, transaction_id: int | None = None,
            notes: str | None = None, evidence_ids: list | str | None = None,
            request_id: str | None = None) -> int:
        import json
        if isinstance(evidence_ids, (list, tuple)):
            evidence_ids = json.dumps(sorted(str(i) for i in evidence_ids))
        self.conn.execute(
            "INSERT INTO decisions (decision_id, case_id, reviewer, decision,"
            " decided_at, transaction_id, notes, evidence_ids, request_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [decision_id, case_id, reviewer, decision, decided_at,
             transaction_id, notes, evidence_ids, request_id])
        return decision_id

    def for_case(self, case_id: int) -> list[dict[str, Any]]:
        return _to_dicts(self.conn.execute(
            "SELECT * FROM decisions WHERE case_id = ? ORDER BY decided_at",
            [case_id]))


class LabelRepository:
    def __init__(self, conn: duckdb.DuckDBPyConnection):
        self.conn = conn

    def add(self, label_id: int, txn_id: int, source: str, value: int,
            effective_at, arrival_at, case_id: int | None = None,
            decision_id: int | None = None, created_at=None) -> int:
        self.conn.execute(
            "INSERT INTO labels (label_id, txn_id, source, value,"
            " effective_at, arrival_at, case_id, decision_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [label_id, txn_id, source, value, effective_at, arrival_at,
             case_id, decision_id, created_at])
        return label_id

    def for_case(self, case_id: int) -> list[dict[str, Any]]:
        return _to_dicts(self.conn.execute(
            "SELECT * FROM labels WHERE case_id = ?", [case_id]))

    def for_transaction(self, txn_id: int) -> list[dict[str, Any]]:
        return _to_dicts(self.conn.execute(
            "SELECT * FROM labels WHERE txn_id = ?", [txn_id]))


class HistoryRepository:
    def __init__(self, conn: duckdb.DuckDBPyConnection):
        self.conn = conn

    def add(self, history_id: int, case_id: int, actor: str, action: str,
            prev_status: str | None, new_status: str | None,
            details: str | None, created_at) -> int:
        self.conn.execute(
            "INSERT INTO case_history VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [history_id, case_id, actor, action, prev_status, new_status,
             details, created_at])
        return history_id

    def for_case(self, case_id: int) -> list[dict[str, Any]]:
        return _to_dicts(self.conn.execute(
            "SELECT * FROM case_history WHERE case_id = ?"
            " ORDER BY created_at, history_id", [case_id]))
