# Case management, immutable decisions, Labels, delayed EntityRisk

# Covers spec categories A-H:
# - A creation · B state machine · C notes · D decisions · E labels ·
# - F EntityRisk point-in-time boundaries · G API semantics · H regression.

import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cases.entityrisk import TS_ANCHOR_UNIX_S, compute_entity_risk, label_is_eligible
from app.cases.service import CaseError, CaseService
from app.cases.state_machine import ALLOWED_TRANSITIONS, TERMINAL_STATES
from app.config import load_settings
from app.storage.db import connect, init_db

MODEL_VERSION = "fraud_xgb_v1-9e2978c"
LAG = 7

def _seed_store(conn):
    # Two covered transactions with evidence; one foreign-evidence txn
    conn.execute(
        "INSERT OR REPLACE INTO risk_predictions VALUES"
        " (?, ?, ?, ?, NULL)", [2987004, MODEL_VERSION, 0.42, "MEDIUM"])
    conn.execute(
        "INSERT OR REPLACE INTO risk_predictions VALUES"
        " (?, ?, ?, ?, NULL)", [2987005, MODEL_VERSION, 0.91, "CRITICAL"])
    for eid, tid in (("ev-a1", 2987004), ("ev-a2", 2987004),
                     ("ev-b1", 2987005)):
        conn.execute(
            "INSERT OR REPLACE INTO evidence VALUES (?, ?, 'NEW_PAIRING',"
            " '{}', 'hash', NULL)", [eid, tid])


@pytest.fixture()
def store(tmp_path):
    conn = init_db(tmp_path / "c.duckdb")
    _seed_store(conn)
    settings = load_settings(environ={
        "FG_BASE_DIR": str(tmp_path),
        "FG_DB_PATH": str(tmp_path / "c.duckdb"),
        "FG_MIN_LABEL_LAG_DAYS": str(LAG)})
    yield conn, settings
    conn.close()


@pytest.fixture()
def svc(store):
    return CaseService(store[0], store[1])


def _new_case(svc, txn=2987004, ev=("ev-a1",)):
    return svc.create_case(txn, "Investigate spike", "analyst-1",
                           list(ev), "req-create")


def _to_investigating(svc, case_id):
    svc.patch_case(case_id, "analyst-1", status="INVESTIGATING")

def test_a_valid_creation(svc):
    out = _new_case(svc)
    got = svc.get_case(out["case_id"])
    assert got["status"] == "NEW" and got["transaction_id"] == 2987004
    assert got["actor"] == "analyst-1" and got["created_at"]
    actions = [h["action"] for h in got["history"]]
    assert actions == ["CREATED"]


def test_a_unknown_transaction_404(svc):
    with pytest.raises(CaseError) as e:
        svc.create_case(1, "t", "a")
    assert e.value.code == "404"


def test_a_invalid_evidence_422(svc):
    with pytest.raises(CaseError) as e:
        svc.create_case(2987004, "t", "a", ["nope"])
    assert e.value.code == "422"


def test_a_foreign_evidence_422(svc):
    with pytest.raises(CaseError) as e:
        svc.create_case(2987004, "t", "a", ["ev-b1"])
    assert e.value.code == "422"


def test_a_duplicate_evidence_ids_422(svc):
    with pytest.raises(CaseError) as e:
        svc.create_case(2987004, "t", "a", ["ev-a1", "ev-a1"])
    assert e.value.code == "422"

def test_b_every_valid_transition(svc):
    legal = [("NEW", "INVESTIGATING"), ("NEW", "ESCALATED"),
             ("INVESTIGATING", "ESCALATED"), ("INVESTIGATING", "INVESTIGATING")]
    for cur, nxt in legal:
        if nxt == cur:
            continue
        assert cur in ALLOWED_TRANSITIONS and nxt in ALLOWED_TRANSITIONS[cur]


def test_b_state_machine_table_exact():
    expected = {
        "NEW": {"INVESTIGATING", "ESCALATED"},
        "INVESTIGATING": {"ESCALATED", "CONFIRMED_FRAUD", "FALSE_POSITIVE"},
        "ESCALATED": {"INVESTIGATING", "CONFIRMED_FRAUD", "FALSE_POSITIVE"},
        "CONFIRMED_FRAUD": {"CLOSED"},
        "FALSE_POSITIVE": {"CLOSED"},
        "CLOSED": set(),
    }
    assert ALLOWED_TRANSITIONS == expected
    assert TERMINAL_STATES == {"CONFIRMED_FRAUD", "FALSE_POSITIVE", "CLOSED"}


def test_b_invalid_transitions_conflict(svc):
    case = _new_case(svc)["case_id"]
    for bad in ("CLOSED", "CONFIRMED_FRAUD", "FALSE_POSITIVE"):
        with pytest.raises(CaseError) as e:
            svc.patch_case(case, "a", status=bad)
        assert e.value.code == "409", bad


def test_b_closed_cannot_reopen(svc):
    case = _new_case(svc)["case_id"]
    _to_investigating(svc, case)
    svc.decide(case, "CONFIRMED_FRAUD", "lead",
               notes="n", evidence_ids=["ev-a1"])
    with pytest.raises(CaseError) as e:
        svc.patch_case(case, "a", status="INVESTIGATING")
    assert e.value.code == "409"


def test_b_terminal_flip_forbidden_via_decision_path(svc):
    """CONFIRMED_FRAUD cannot become FALSE_POSITIVE: second decision rejected."""
    case = _new_case(svc)["case_id"]
    _to_investigating(svc, case)
    d1 = svc.decide(case, "CONFIRMED_FRAUD", "lead", "n", ["ev-a1"])
    with pytest.raises(CaseError) as e:
        svc.decide(case, "FALSE_POSITIVE", "lead", "flip", ["ev-a2"])
    assert e.value.code == "409"
    # original decision unchanged
    got = svc.get_case(case)
    assert len(got["decisions"]) == 1
    assert got["decisions"][0]["decision_id"] == d1["decision_id"]
    assert got["decisions"][0]["decision"] == "CONFIRMED_FRAUD"

def test_c_note_mutation_and_history_retained(svc):
    case = _new_case(svc)["case_id"]
    svc.patch_case(case, "a1", note="first look")
    svc.patch_case(case, "a2", note="second look")
    got = svc.get_case(case)
    notes = [n["note"] for n in got["notes"]]
    assert notes == ["first look", "second look"]      # history retained
    assert [n["actor"] for n in got["notes"]] == ["a1", "a2"]

def test_d_valid_confirmed_fraud(svc):
    case = _new_case(svc)["case_id"]
    _to_investigating(svc, case)
    out = svc.decide(case, "CONFIRMED_FRAUD", "lead", "confirmed",
                     ["ev-a1", "ev-a2"], "req-dec")
    got = svc.get_case(case)
    assert got["status"] == "CONFIRMED_FRAUD"
    assert out["decision_id"] == got["decisions"][0]["decision_id"]
    assert got["decisions"][0]["evidence_ids"] == ["ev-a1", "ev-a2"]
    assert got["decisions"][0]["request_id"] == "req-dec"


def test_d_valid_false_positive_from_escalated(svc):
    case = _new_case(svc)["case_id"]
    _to_investigating(svc, case)
    svc.patch_case(case, "a", status="ESCALATED")
    svc.decide(case, "FALSE_POSITIVE", "lead", None, ["ev-a1"])
    assert svc.get_case(case)["status"] == "FALSE_POSITIVE"
    label = svc.get_case(case)["label"]
    assert label["value"] == 0


def test_d_decision_only_from_investigating_or_escalated(svc):
    case = _new_case(svc)["case_id"]          # NEW
    with pytest.raises(CaseError) as e:
        svc.decide(case, "CONFIRMED_FRAUD", "lead", None, ["ev-a1"])
    assert e.value.code == "409"


def test_d_missing_evidence_acknowledgement_422(svc):
    case = _new_case(svc)["case_id"]
    _to_investigating(svc, case)
    with pytest.raises(CaseError) as e:
        svc.decide(case, "CONFIRMED_FRAUD", "lead", None, [])
    assert e.value.code == "422"


def test_d_unknown_evidence_422(svc):
    case = _new_case(svc)["case_id"]
    _to_investigating(svc, case)
    with pytest.raises(CaseError) as e:
        svc.decide(case, "CONFIRMED_FRAUD", "lead", None, ["ghost"])
    assert e.value.code == "422"


def test_d_duplicate_decision_rejected_and_old_intact(svc):
    case = _new_case(svc)["case_id"]
    _to_investigating(svc, case)
    first = svc.decide(case, "CONFIRMED_FRAUD", "lead", "v1", ["ev-a1"])
    with pytest.raises(CaseError) as e:
        svc.decide(case, "CONFIRMED_FRAUD", "lead", "v2", ["ev-a2"])
    assert e.value.code == "409"
    decisions = svc.get_case(case)["decisions"]
    assert len(decisions) == 1
    assert decisions[0]["notes"] == "v1"                    # old intact
    assert decisions[0]["decision_id"] == first["decision_id"]


def test_d_patch_into_decision_states_forbidden(svc):
    case = _new_case(svc)["case_id"]
    _to_investigating(svc, case)
    with pytest.raises(CaseError) as e:
        svc.patch_case(case, "a", status="CONFIRMED_FRAUD")
    assert e.value.code == "409"

def test_e_exactly_one_label_referencing_case_and_decision(svc):
    case = _new_case(svc)["case_id"]
    _to_investigating(svc, case)
    dec = svc.decide(case, "CONFIRMED_FRAUD", "lead", None, ["ev-a1"])
    got = svc.get_case(case)
    assert got["label"] is not None
    rows = svc.conn.execute(
        "SELECT COUNT(*) FROM labels WHERE case_id=?", [case]).fetchone()[0]
    assert rows == 1
    row = svc.conn.execute(
        "SELECT case_id, decision_id, arrival_at FROM labels WHERE label_id=?",
        [got["label"]["label_id"]]).fetchone()
    assert int(row[0]) == case and int(row[1]) == dec["decision_id"]
    assert row[2] is not None                              # arrival recorded
    assert got["label"]["value"] == 1                      # fraud label

def _link_entity(conn, entity_type, entity_key, txn_ids):
    for tid in txn_ids:
        conn.execute("INSERT INTO graph_links VALUES (?, ?, ?, ?)",
                     [entity_type, entity_key, tid, 1000])


def _insert_label(conn, txn_id, value, arrival_txn_s):
    arrival = datetime.fromtimestamp(
        TS_ANCHOR_UNIX_S + arrival_txn_s, tz=UTC).replace(tzinfo=None)
    conn.execute(
        "INSERT OR REPLACE INTO labels VALUES (?, ?, 'reviewer', ?, ?, ?,"
        " NULL, NULL, NULL)",
        [int(uuid.uuid4().int % 2 ** 62), txn_id, value, arrival, arrival])


JAN10 = 40 * 86400     # anchor Dec 1 → Jan 10
JAN12 = 42 * 86400     # Jan 12
JAN20 = 50 * 86400     # Jan 20
DAY = 86400


def _risk_fixture(store):
    conn = store[0]
    _link_entity(conn, "CARD", "E1", [101])
    _insert_label(conn, 101, value=1, arrival_txn_s=JAN12)


def test_f_too_new_label_does_not_contribute(store, svc):
    _risk_fixture(store)
    r = compute_entity_risk(store[0], "CARD", "E1", JAN10, LAG)
    # Case A: T=Jan10, boundary=Jan3; arrival Jan12 → excluded
    assert r.entity_total_labeled_count == 0 and r.fraud_rate is None


def test_f_eligible_label_contributes(store, svc):
    _risk_fixture(store)
    r = compute_entity_risk(store[0], "CARD", "E1", JAN20, LAG)
    # Case B: T=Jan20, boundary=Jan13; arrival Jan12 ≤ boundary → included
    assert r.entity_total_labeled_count == 1
    assert r.entity_fraud_count == 1 and r.fraud_rate == 1.0


def test_f_exact_boundary_inclusive(store, svc):
    _risk_fixture(store)
    t_exact = JAN12 + 7 * DAY          # boundary lands exactly on arrival
    r = compute_entity_risk(store[0], "CARD", "E1", t_exact, LAG)
    # Case C: arrival_at == T - MIN_LABEL_LAG → IS eligible
    assert r.entity_total_labeled_count == 1


def test_f_one_unit_after_boundary_exclusive(store, svc):
    conn = store[0]
    _link_entity(conn, "CARD", "E2", [102])
    _insert_label(conn, 102, value=1, arrival_txn_s=JAN12 + 1)
    t_exact = JAN12 + 7 * DAY
    r = compute_entity_risk(conn, "CARD", "E2", t_exact, LAG)
    # Case D: arrival one second AFTER the boundary → NOT eligible
    assert r.entity_total_labeled_count == 0 and r.fraud_rate is None


def test_f_deterministic_aggregation(store, svc):
    _risk_fixture(store)
    a = compute_entity_risk(store[0], "CARD", "E1", JAN20, LAG)
    b = compute_entity_risk(store[0], "CARD", "E1", JAN20, LAG)
    assert a == b


def test_f_no_backward_leak_multiple_entities(store, svc):
    conn = store[0]
    _link_entity(conn, "DEVICE", "D1", [201])
    _insert_label(conn, 201, value=1, arrival_txn_s=JAN12)
    before = compute_entity_risk(conn, "DEVICE", "D1", JAN10, LAG)
    after = compute_entity_risk(conn, "DEVICE", "D1", JAN20, LAG)
    assert before.entity_fraud_count == 0
    assert after.entity_fraud_count == 1


def test_f_pure_boundary_predicate():
    lag_s = LAG * DAY
    assert label_is_eligible(1000, 1000 + lag_s, LAG) is True        # exact
    assert label_is_eligible(1001, 1000 + lag_s, LAG) is False       # +1s
    assert label_is_eligible(999, 1000 + lag_s, LAG) is True


def test_f_decision_label_microsecond_exact_boundary(store, svc):
    """Regression: decide()-produced labels must be whole-second so the
    inclusive boundary at T - MIN_LABEL_LAG is reachable exactly."""
    conn = store[0]
    _link_entity(conn, "CARD", "E9", [2987004])   # same txn as the case
    case = svc.create_case(2987004, "t", "a", ["ev-a1"])["case_id"]
    _to_investigating(svc, case)
    dec = svc.decide(case, "CONFIRMED_FRAUD", "lead", None, ["ev-a1"])
    arrival = conn.execute(
        "SELECT arrival_at FROM labels WHERE label_id=?",
        [dec["label_id"]]).fetchone()[0]
    assert arrival.microsecond == 0                      # whole second
    elig_ts = round(arrival.replace(tzinfo=UTC).timestamp()
                        - TS_ANCHOR_UNIX_S) + LAG * 86400
    before = compute_entity_risk(conn, "CARD", "E9", elig_ts - 1, LAG)
    at = compute_entity_risk(conn, "CARD", "E9", elig_ts, LAG)
    assert before.entity_total_labeled_count == 0
    assert at.entity_total_labeled_count == 1            # inclusive

def test_g_api_full_lifecycle(client):
    seed_conn = connect(client.app.state.settings.db_path)
    _seed_store(seed_conn)
    seed_conn.close()
    c = client.post("/cases", json={
        "transaction_id": 2987004, "title": "Queue review",
        "actor": "analyst", "evidence_ids": ["ev-a1"],
        "request_id": "req-api-1"})
    assert c.status_code == 201
    case_id = c.json()["case_id"]
    assert client.get(f"/cases/{case_id}").status_code == 200
    q = client.get("/cases", params={"status": "NEW"}).json()
    assert any(x["case_id"] == case_id for x in q["cases"])
    assert client.patch(f"/cases/{case_id}", json={
        "actor": "analyst", "status": "INVESTIGATING"}).status_code == 200
    d = client.post(f"/cases/{case_id}/decision", json={
        "decision": "CONFIRMED_FRAUD", "actor": "lead", "notes": "ok",
        "evidence_ids": ["ev-a1"], "request_id": "req-api-2"})
    assert d.status_code == 201
    detail = client.get(f"/cases/{case_id}").json()
    assert detail["status"] == "CONFIRMED_FRAUD" and detail["label"]
    assert client.patch(f"/cases/{case_id}", json={
        "actor": "closer", "status": "CLOSED"}).status_code == 200


def test_g_api_errors(client):
    seed_conn = connect(client.app.state.settings.db_path)
    _seed_store(seed_conn)
    seed_conn.close()
    assert client.post("/cases", json={
        "transaction_id": 424242, "title": "x",
        "actor": "a"}).status_code == 404                       # unknown txn
    ok = client.post("/cases", json={
        "transaction_id": 2987005, "title": "x",
        "actor": "a", "evidence_ids": ["ev-b1"]})
    cid = ok.json()["case_id"]
    assert client.post("/cases", json={                         # foreign ev
        "transaction_id": 2987004, "title": "x", "actor": "a",
        "evidence_ids": ["ev-b1"]}).status_code == 422
    assert client.get("/cases/999999999").status_code == 404
    assert client.get("/cases").status_code == 200
    assert client.post(f"/cases/{cid}/decision", json={
        "decision": "CONFIRMED_FRAUD", "actor": "l",
        "evidence_ids": []}).status_code == 422                 # no ack
    assert client.patch(f"/cases/{cid}", json={
        "actor": "a", "status": "CLOSED"}).status_code == 409   # NEW→CLOSED
    dup = client.post(f"/cases/{cid}/decision", json={
        "decision": "CONFIRMED_FRAUD", "actor": "l",
        "evidence_ids": ["ev-b1"]})                             # from NEW
    assert dup.status_code == 409


def test_g_api_503_when_storage_uninitialized(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app
    s = load_settings(environ={"FG_BASE_DIR": str(tmp_path),
                               "FG_DB_PATH": str(tmp_path / "none.duckdb")})
    c = TestClient(create_app(s))
    assert c.post("/cases", json={
        "transaction_id": 1, "title": "x", "actor": "a"}).status_code == 503
    assert client_get_status(c, "/cases") == 503


def client_get_status(c, path):
    return c.get(path).status_code

def test_h_model_artifact_untouched():
    import json
    from pathlib import Path as _P
    meta = json.loads(
        _P("models/fraud_xgb_v1-9e2978c.metadata.json").read_text())
    feats = json.loads(
        _P("models/fraud_xgb_v1-9e2978c.features.json").read_text())
    assert meta["feature_count"] == 438 == len(feats)
    assert meta["model_version"] == MODEL_VERSION
    assert feats[-6:] == ["amt_z_card", "amt_z_device", "hour_dev_card",
                          "hour_dev_device", "hours_since_last_card",
                          "hours_since_last_device"]
    assert not any("entity_risk" in f or "label" in f.lower() for f in feats)


@pytest.mark.real_data
def test_h_graph_links_unchanged():
    n = pq.ParquetFile("data/processed/graph_links.parquet").metadata.num_rows
    assert n == 254777


@pytest.mark.real_data
def test_h_production_features_unchanged():
    n = pq.ParquetFile(
        "data/processed/production_features.parquet").metadata.num_rows
    assert n == 144233


def test_h_evidence_engine_version_unchanged():
    from app.evidence.models import EVIDENCE_ENGINE_VERSION
    assert EVIDENCE_ENGINE_VERSION == "v1"
