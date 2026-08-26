from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["evidence"])

@router.get("/transactions/{transaction_id}/evidence")
def get_evidence(transaction_id: int, request: Request):
    settings = request.app.state.settings
    # check model and graph availability? If missing, 503
    try:
        from app.evidence.service import generate_evidence
        model_risk, evidence = generate_evidence(transaction_id, settings)
        # Build response
        ev_list = []
        for ev in evidence:
            ev_list.append({
                "evidence_id": ev.evidence_id,
                "transaction_id": ev.transaction_id,
                "evidence_type": ev.evidence_type,
                "title": ev.title,
                "description": ev.description,
                "details": ev.details,
                "severity": ev.severity,
                "provenance": ev.provenance,
                "evidence_hash": ev.evidence_hash,
                "generated_at": ev.generated_at,
            })
        # fetch graph version/params hash if available
        try:
            from app.graph.service import expand_transaction
            graph_res = expand_transaction(transaction_id, settings=settings)
            graph_version = graph_res["graph_version"]
            params_hash = graph_res["params_hash"]
        except Exception:  # noqa: BLE001 - graph metadata is optional context
            graph_version = None
            params_hash = None
        return {
            "transaction_id": transaction_id,
            "model_risk": model_risk,
            "evidence": ev_list,
            "evidence_engine_version": "v1",
            "graph_version": graph_version,
            "params_hash": params_hash,
        }
    except KeyError as e:
        if "404" in str(e):
            raise HTTPException(status_code=404, detail="transaction not found")
        raise HTTPException(status_code=404, detail="transaction not found")
    except ValueError as e:
        if "422" in str(e):
            raise HTTPException(status_code=422, detail="transaction exists but required production/investigation coverage is unavailable")
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        if "503" in str(e):
            raise HTTPException(status_code=503, detail="required storage/index/model unavailable")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as ex:  # noqa: BLE001 - last-resort mapping to 500
        # distinguish 404/422 already handled
        raise HTTPException(status_code=500, detail=str(ex))
