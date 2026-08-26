# Transaction queue: `GET /transactions?min_score=&window=`
# Smallest read-only implementation of the queue contract for the dashboard: ranks scored transactions from the EXISTING `risk_predictions` table and flags evidence availability via an EXISTS probe on `evidence`. No new tables, no model/graph/evidence logic changes.

from fastapi import APIRouter, Query, Request

from app.storage.db import connect

router = APIRouter(tags=["transactions"])

VALID_BANDS = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


@router.get("/transactions")
def list_transactions(request: Request,
                      min_score: float | None = Query(default=None, ge=0.0,
                                                      le=1.0),
                      band: str | None = None,
                      has_evidence: bool | None = None,
                      limit: int = Query(default=25, ge=1, le=200)):
    settings = request.app.state.settings
    if not settings.db_path.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=503,
                            detail="transaction storage unavailable"
                                   " (uninitialized)")
    if band is not None and band.upper() not in VALID_BANDS:
        from fastapi import HTTPException
        raise HTTPException(status_code=422,
                            detail=f"band must be one of {sorted(VALID_BANDS)}")
    try:
        conn = connect(settings.db_path)
    except Exception:  # noqa: BLE001 - storage failure maps to 503
        from fastapi import HTTPException
        raise HTTPException(status_code=503,
                            detail="transaction storage unavailable") from None
    try:
        sql = ("SELECT transaction_id, model_version, risk_score, risk_band,"
               " EXISTS(SELECT 1 FROM evidence e WHERE e.txn_id ="
               " risk_predictions.transaction_id) AS has_evidence"
               " FROM risk_predictions")
        where, params = [], []
        if min_score is not None:
            where.append("risk_score >= ?")
            params.append(min_score)
        if band is not None:
            where.append("UPPER(risk_band) = ?")
            params.append(band.upper())
        if has_evidence is not None:
            where.append("EXISTS(SELECT 1 FROM evidence e WHERE e.txn_id ="
                         " risk_predictions.transaction_id) = ?")
            params.append(1 if has_evidence else 0)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += (" ORDER BY risk_score DESC, transaction_id LIMIT ?")
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
    except Exception:  # noqa: BLE001 - query failure maps to 503
        from fastapi import HTTPException
        raise HTTPException(status_code=503,
                            detail="transaction storage unavailable") from None
    finally:
        conn.close()
    return {
        "transactions": [
            {"transaction_id": int(r[0]), "model_version": r[1],
             "risk_score": float(r[2]), "risk_band": r[3],
             "has_evidence": bool(r[4])} for r in rows],
        "count": len(rows),
        "request_id": None,
    }
