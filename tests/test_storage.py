from app.storage import db
from app.storage.repositories import (
    CaseRepository,
    DecisionRepository,
    EvidenceRepository,
    TransactionRepository,
)


def test_init_db_creates_schema(tmp_path):
    conn = db.init_db(tmp_path / "t.duckdb")
    assert db.readiness(conn)
    assert db.required_tables().issubset(db.existing_tables(conn))
    conn.close()


def test_transaction_roundtrip_and_reopen(tmp_path):
    path = tmp_path / "t.duckdb"
    conn = db.init_db(path)
    repo = TransactionRepository(conn)
    repo.upsert({"txn_id": 1, "ts": 1000, "amount": 9.5, "score": 0.9,
                 "is_fraud": 0})
    got = repo.get_by_id(1)
    assert got == {"txn_id": 1, "ts": 1000, "amount": 9.5, "score": 0.9,
                   "is_fraud": 0}
    conn.close()

    conn2 = db.connect(path)
    assert TransactionRepository(conn2).get_by_id(1)["score"] == 0.9
    conn2.close()


def test_top_by_score_ordering(tmp_path):
    conn = db.init_db(tmp_path / "t.duckdb")
    repo = TransactionRepository(conn)
    for i, score in enumerate([0.1, 0.9, 0.5]):
        repo.upsert({"txn_id": i, "ts": i, "amount": 1.0, "score": score,
                     "is_fraud": 0})
    top = repo.top_by_score(2)
    assert [r["txn_id"] for r in top] == [1, 2]
    conn.close()


def test_evidence_roundtrip(tmp_path):
    conn = db.init_db(tmp_path / "t.duckdb")
    repo = EvidenceRepository(conn)
    rec = {"evidence_id": "ev-1", "txn_id": 42,
           "evidence_type": "NEW_PAIRING", "payload": "{}",
           "evidence_hash": "abc", "generated_at": None}
    repo.add(rec)
    rows = repo.for_transaction(42)
    assert len(rows) == 1
    assert rows[0]["evidence_type"] == "NEW_PAIRING"
    conn.close()


def test_case_decision_lifecycle(tmp_path):
    conn = db.init_db(tmp_path / "t.duckdb")
    cases = CaseRepository(conn)
    decisions = DecisionRepository(conn)
    cases.create(1, subject_txn_id=99, status="NEW", opened_at=None)
    assert cases.get(1)["status"] == "NEW"
    cases.update_status(1, "CONFIRMED_FRAUD")
    assert cases.get(1)["status"] == "CONFIRMED_FRAUD"
    decisions.add(1, case_id=1, reviewer="analyst",
                  decision="CONFIRMED_FRAUD", decided_at=None)
    decisions.add(2, case_id=1, reviewer="lead", decision="ESCALATED",
                  decided_at=None)
    assert len(decisions.for_case(1)) == 2
    conn.close()
