# Case management service — state machine enforcement, immutable decisions, Label creation, append-only audit history.
# Sits above the storage layer; routers translate its typed errors into HTTP.

import json
import uuid
from datetime import UTC, datetime

import duckdb

from app.cases.state_machine import DECISION_STATES, TERMINAL_STATES, VALID_STATUSES, can_transition
from app.config import get_settings


class CaseError(Exception):
    def __init__(self, code: str, detail: str):
        self.code = code          # "404" | "409" | "422" | "503"
        self.detail = detail
        super().__init__(detail)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _json_list(ids) -> str:
    return json.dumps(sorted({str(i) for i in ids}))


class CaseService:
    def __init__(self, conn: duckdb.DuckDBPyConnection, settings=None):
        self.conn = conn
        self.settings = settings or get_settings()

    # ---------------- audit ----------------
    def _history(self, case_id: int, actor: str, action: str,
                 prev: str | None, new: str | None,
                 details: dict | None = None) -> int:
        # Monotonic id keeps the append-only trail chronologically ordered
        # even when multiple actions land in the same microsecond.
        hid = int(self.conn.execute(
            "SELECT COALESCE(MAX(history_id), 0) + 1 FROM case_history"
        ).fetchone()[0])
        self.conn.execute(
            "INSERT INTO case_history VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [hid, case_id, actor, action, prev, new,
             json.dumps(details or {}), _now()])
        return hid

    # ---------------- creation ----------------
    def create_case(self, transaction_id: int, title: str, actor: str,
                    evidence_ids: list[str] | None = None,
                    request_id: str | None = None) -> dict:
        if not title or not actor:
            raise CaseError("422", "title and actor are required")
        ev_ids = evidence_ids or []
        if len(ev_ids) != len(set(ev_ids)):
            raise CaseError("422", "duplicate evidence_ids in request")
        # transaction must exist in production/investigation coverage
        row = self.conn.execute(
            "SELECT transaction_id FROM risk_predictions WHERE transaction_id = ?",
            [transaction_id]).fetchone()
        if row is None:
            raw = self.conn.execute(
                "SELECT COUNT(*) FROM evidence WHERE txn_id = ?",
                [transaction_id]).fetchone()[0]
            if raw == 0:
                raise CaseError("404", f"transaction {transaction_id} not found")
            raise CaseError("422",
                            "transaction exists but has no production coverage")
        # evidence must exist and belong to the transaction
        for eid in ev_ids:
            r = self.conn.execute(
                "SELECT txn_id FROM evidence WHERE evidence_id = ?", [eid]).fetchone()
            if r is None:
                raise CaseError("422", f"unknown evidence_id {eid}")
            if int(r[0]) != int(transaction_id):
                raise CaseError("422",
                                f"evidence {eid} belongs to another transaction")
        case_id = int(uuid.uuid4().int % (2 ** 62))
        now = _now()
        self.conn.execute(
            "INSERT INTO cases (case_id, subject_txn_id, status, opened_at,"
            " title, actor, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [case_id, transaction_id, "NEW", now, title, actor, now])
        self._history(case_id, actor, "CREATED", None, "NEW",
                      {"title": title, "evidence_ids": ev_ids,
                       "request_id": request_id})
        return {"case_id": case_id, "transaction_id": transaction_id,
                "status": "NEW", "title": title, "actor": actor,
                "created_at": now.isoformat(), "request_id": request_id}

    # ---------------- retrieval ----------------
    def list_cases(self, status: str | None = None) -> list[dict]:
        if status is not None and status not in VALID_STATUSES:
            raise CaseError("422", f"unknown status {status!r}")
        sql = ("SELECT c.case_id, c.subject_txn_id AS transaction_id, c.status,"
               " c.title, c.actor, c.opened_at, c.updated_at"
               " FROM cases c")
        params: list = []
        if status is not None:
            sql += " WHERE c.status = ?"
            params.append(status)
        sql += " ORDER BY c.opened_at DESC, c.case_id"
        rows = self.conn.execute(sql, params).fetchall()
        out = []
        for cid, tid, st, title, actor, opened, updated in rows:
            risk = self.conn.execute(
                "SELECT risk_score, risk_band, model_version FROM risk_predictions"
                " WHERE transaction_id = ?", [tid]).fetchone()
            linked_ev = self._created_evidence(cid)
            dec = self.conn.execute(
                "SELECT decision_id, decision, decided_at FROM decisions"
                " WHERE case_id = ? ORDER BY decided_at DESC LIMIT 1",
                [cid]).fetchone()
            out.append({
                "case_id": int(cid), "transaction_id": int(tid),
                "status": st, "title": title, "actor": actor,
                "created_at": opened.isoformat() if opened else None,
                "updated_at": updated.isoformat() if updated else None,
                "model_risk": ({"risk_score": risk[0], "risk_band": risk[1],
                                "model_version": risk[2]} if risk else None),
                "evidence_count": len(linked_ev),
                "latest_decision": ({"decision_id": int(dec[0]),
                                     "decision": dec[1],
                                     "decided_at": dec[2].isoformat()
                                     if dec[2] else None} if dec else None),
            })
        return out

    def _created_evidence(self, case_id: int) -> list[str]:
        rows = self.conn.execute(
            "SELECT details FROM case_history WHERE case_id=? AND action='CREATED'",
            [case_id]).fetchall()
        ids: set[str] = set()
        for (d,) in rows:
            try:
                ids.update(json.loads(d or "{}").get("evidence_ids", []))
            except (ValueError, TypeError):
                pass
        return sorted(ids)

    def get_case(self, case_id: int) -> dict:
        c = self.conn.execute(
            "SELECT case_id, subject_txn_id, status, title, actor, opened_at,"
            " updated_at FROM cases WHERE case_id = ?", [case_id]).fetchone()
        if c is None:
            raise CaseError("404", f"case {case_id} not found")
        cid, tid, status, title, actor, opened, updated = c
        risk = self.conn.execute(
            "SELECT risk_score, risk_band, model_version FROM risk_predictions"
            " WHERE transaction_id = ?", [tid]).fetchone()
        linked_ev = self._created_evidence(cid)
        evidence_rows = []
        for eid in linked_ev:
            e = self.conn.execute(
                "SELECT evidence_id, txn_id, evidence_type, payload,"
                " evidence_hash, generated_at FROM evidence WHERE evidence_id=?",
                [eid]).fetchone()
            if e:
                evidence_rows.append({
                    "evidence_id": e[0], "transaction_id": int(e[1]),
                    "evidence_type": e[2],
                    "details_json": e[3], "evidence_hash": e[4],
                    "generated_at": e[5].isoformat() if e[5] else None})
        notes = self.conn.execute(
            "SELECT actor, details, created_at FROM case_history"
            " WHERE case_id=? AND action='NOTE_ADDED' ORDER BY created_at, history_id",
            [case_id]).fetchall()
        history = self.conn.execute(
            "SELECT history_id, actor, action, prev_status, new_status,"
            " details, created_at FROM case_history WHERE case_id=?"
            " ORDER BY created_at, history_id", [case_id]).fetchall()
        decisions = self.conn.execute(
            "SELECT decision_id, reviewer, decision, decided_at, notes,"
            " evidence_ids, request_id FROM decisions WHERE case_id=?"
            " ORDER BY decided_at, decision_id", [case_id]).fetchall()
        label = self.conn.execute(
            "SELECT label_id, value, arrival_at, effective_at, source"
            " FROM labels WHERE case_id=?", [case_id]).fetchone()
        return {
            "case_id": int(cid), "transaction_id": int(tid),
            "status": status, "title": title, "actor": actor,
            "created_at": opened.isoformat() if opened else None,
            "updated_at": updated.isoformat() if updated else None,
            "model_risk": ({"risk_score": risk[0], "risk_band": risk[1],
                            "model_version": risk[2]} if risk else None),
            "evidence": evidence_rows,
            "notes": [{"actor": a, "note": json.loads(d or "{}").get("note", ""),
                       "created_at": t.isoformat() if t else None}
                      for a, d, t in notes],
            "history": [{"history_id": int(h[0]), "actor": h[1],
                         "action": h[2], "prev_status": h[3], "new_status": h[4],
                         "details": json.loads(h[5] or "{}"),
                         "created_at": h[6].isoformat() if h[6] else None}
                        for h in history],
            "decisions": [{"decision_id": int(d[0]), "reviewer": d[1],
                           "decision": d[2],
                           "decided_at": d[3].isoformat() if d[3] else None,
                           "notes": d[4], "evidence_ids":
                           json.loads(d[5]) if d[5] else [],
                           "request_id": d[6]} for d in decisions],
            "label": ({"label_id": int(label[0]), "value": int(label[1]),
                       "arrival_at": label[2].isoformat() if label[2] else None,
                       "effective_at": label[3].isoformat() if label[3] else None,
                       "source": label[4]} if label else None),
        }

    # ---------------- mutations ----------------
    def patch_case(self, case_id: int, actor: str, status: str | None = None,
                   note: str | None = None,
                   request_id: str | None = None) -> dict:
        cur_row = self.conn.execute(
            "SELECT status FROM cases WHERE case_id = ?", [case_id]).fetchone()
        if cur_row is None:
            raise CaseError("404", f"case {case_id} not found")
        current = cur_row[0]
        changed = False
        if note is not None and note.strip():
            self._history(case_id, actor, "NOTE_ADDED", current, current,
                          {"note": note, "request_id": request_id})
            changed = True
        if status is not None:
            if status not in VALID_STATUSES:
                raise CaseError("422", f"unknown status {status!r}")
            if status in DECISION_STATES:
                # Decision states are reachable ONLY through the immutable
                # decision endpoint (evidence acknowledgement + Label).
                raise CaseError(
                    "409",
                    f"{status} is reachable only via"
                    f" POST /cases/{case_id}/decision")
            if status == current:
                raise CaseError("409", f"case already in status {status}")
            if not can_transition(current, status):
                raise CaseError(
                    "409", f"illegal transition {current} -> {status}")
            now = _now()
            self.conn.execute(
                "UPDATE cases SET status=?, updated_at=? WHERE case_id=?",
                [status, now, case_id])
            self._history(case_id, actor, "STATUS_CHANGED", current, status,
                          {"request_id": request_id})
            changed = True
            current = status
        if not changed:
            raise CaseError("422", "nothing to update: provide status and/or note")
        return {"case_id": case_id, "status": current}

    def decide(self, case_id: int, decision: str, actor: str,
               notes: str | None = None, evidence_ids: list[str] | None = None,
               request_id: str | None = None) -> dict:
        if decision not in DECISION_STATES:
            raise CaseError("422",
                            f"decision must be one of {sorted(DECISION_STATES)}")
        if not actor:
            raise CaseError("422", "actor is required")
        ev_ids = evidence_ids or []
        if not ev_ids:
            raise CaseError("422",
                            "evidence acknowledgement required: evidence_ids empty")
        if len(ev_ids) != len(set(ev_ids)):
            raise CaseError("422", "duplicate evidence_ids in request")
        row = self.conn.execute(
            "SELECT subject_txn_id, status FROM cases WHERE case_id=?",
            [case_id]).fetchone()
        if row is None:
            raise CaseError("404", f"case {case_id} not found")
        transaction_id, status = int(row[0]), row[1]
        if status not in ("INVESTIGATING", "ESCALATED"):
            raise CaseError(
                "409",
                f"terminal decision allowed only from INVESTIGATING/ESCALATED,"
                f" case is {status}")
        existing = self.conn.execute(
            "SELECT COUNT(*) FROM decisions WHERE case_id=? AND decision IN"
            " ('CONFIRMED_FRAUD','FALSE_POSITIVE')",
            [case_id]).fetchone()[0]
        if existing:
            raise CaseError("409", "a terminal decision already exists for this"
                                   " case; corrections require review policy,"
                                   " decisions are immutable")
        for eid in ev_ids:
            r = self.conn.execute(
                "SELECT txn_id FROM evidence WHERE evidence_id=?", [eid]).fetchone()
            if r is None:
                raise CaseError("422", f"unknown evidence_id {eid}")
            if int(r[0]) != transaction_id:
                raise CaseError("422",
                                f"evidence {eid} belongs to another transaction")
        decision_id = int(uuid.uuid4().int % (2 ** 62))
        # Whole-second timestamps: the EntityRisk query clock (as_of_ts) is
        # integer seconds, so a mid-second arrival could otherwise NEVER
        # satisfy arrival_at <= T - MIN_LABEL_LAG at its own boundary
        # (whole-second truncation guarantees boundary eligibility).
        now = _now().replace(microsecond=0)
        # Immutable insert — no UPDATE path exists for decisions anywhere.
        self.conn.execute(
            "INSERT INTO decisions (decision_id, case_id, reviewer, decision,"
            " decided_at, transaction_id, notes, evidence_ids, request_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [decision_id, case_id, actor, decision, now, transaction_id,
             notes, _json_list(ev_ids), request_id])
        # status -> terminal decision state
        self.conn.execute(
            "UPDATE cases SET status=?, updated_at=? WHERE case_id=?",
            [decision, now, case_id])
        # exactly one Label referencing case + decision
        label_id = int(uuid.uuid4().int % (2 ** 62))
        value = 1 if decision == "CONFIRMED_FRAUD" else 0
        self.conn.execute(
            "INSERT INTO labels (label_id, txn_id, source, value, effective_at,"
            " arrival_at, case_id, decision_id, created_at)"
            " VALUES (?, ?, 'reviewer', ?, ?, ?, ?, ?, ?)",
            [label_id, transaction_id, value, now, now, case_id, decision_id,
             now])
        self._history(case_id, actor, "DECISION", status, decision,
                      {"decision_id": decision_id, "label_id": label_id,
                       "evidence_ids": ev_ids, "request_id": request_id})
        return {"decision_id": decision_id, "case_id": case_id,
                "transaction_id": transaction_id, "decision": decision,
                "status": decision, "label_id": label_id,
                "decided_at": now.isoformat(), "request_id": request_id}

    # ---------------- integrity helpers (used by tests/audit) --------------
    def decision_count(self, case_id: int) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM decisions WHERE case_id=?",
            [case_id]).fetchone()[0]

    def terminal_states(self) -> set[str]:
        return set(TERMINAL_STATES)
