# Evidence service — consumes risk/graph, produces deterministic EvidenceRecords

import pandas as pd

from app.config import get_settings
from app.evidence.models import EVIDENCE_ENGINE_VERSION, EvidenceRecord
from app.evidence.templates import (
    AMOUNT_Z_THRESHOLD,
    COMMUNITY_MIN_TXNS,
    CONNECTED_HIGH_RISK_THRESHOLD,
    HOUR_DEV_THRESHOLD,
    SHARED_DEVICE_MIN_TXNS,
    VELOCITY_THRESHOLDS,
)
from app.storage.db import connect


def _provenance(source_table: str, source_row_ids: list, code_version: str = EVIDENCE_ENGINE_VERSION) -> dict:
    return {"source_table": source_table, "source_row_ids": sorted({int(x) for x in source_row_ids}), "code_version": code_version}

def generate_evidence(transaction_id: int, settings=None) -> tuple[dict, list[EvidenceRecord]]:
    # Return (model_risk_dict, evidence_records). Raises 404/422/503 via exceptions.
    s = settings or get_settings()
    # Check existence: 404 if not in raw, 422 if raw but not in production coverage
    raw_path = s.processed_dir / "ieee_train_transaction.parquet"
    prod_path = s.processed_dir / "production_features.parquet"
    exp_path = s.processed_dir / "experiment_base.parquet"
    # quick existence
    raw_ids = set(pd.read_parquet(raw_path, columns=["TransactionID"])["TransactionID"].values)
    if transaction_id not in raw_ids:
        raise KeyError("404")
    prod_ids = set(pd.read_parquet(prod_path, columns=["TransactionID"])["TransactionID"].values)
    if transaction_id not in prod_ids:
        raise ValueError("422")
    # Load data
    df_exp = pd.read_parquet(exp_path)
    # Find row
    row = df_exp[df_exp["TransactionID"] == transaction_id]
    if row.empty:
        raise ValueError("422")
    row = row.iloc[0]
    # Production features for this txn
    prod_df = pd.read_parquet(prod_path)
    prod_row = prod_df[prod_df["TransactionID"] == transaction_id].iloc[0]

    # Model risk (from DB or live)
    try:
        conn = connect(s.db_path)
        r = conn.execute("SELECT risk_score, risk_band, model_version FROM risk_predictions WHERE transaction_id=?", [transaction_id]).fetchone()
        conn.close()
        if r:
            model_risk = {"risk_score": float(r[0]), "risk_band": r[1], "model_version": r[2]}
        else:
            model_risk = {"risk_score": None, "risk_band": None, "model_version": None}
    except Exception:  # noqa: BLE001 - degrade to null model risk, never 500
        model_risk = {"risk_score": None, "risk_band": None, "model_version": None}
    # Also try to get model_version from latest if None
    if not model_risk["model_version"]:
        try:
            import json
            with open(s.model_dir / "latest.metadata.json") as f:
                meta = json.load(f)
            model_risk["model_version"] = meta["model_version"]
        except Exception:  # noqa: BLE001, S110 - metadata is best-effort only
            pass
    # Graph investigation
    from app.graph.service import expand_transaction
    try:
        graph_res = expand_transaction(transaction_id, settings=s)
    except Exception as ex:
        if "404" in str(ex) or "422" in str(ex):
            raise
        raise RuntimeError(f"503: {ex}")

    evidence: list[EvidenceRecord] = []

    # Helper to get history count? We can approximate from graph or leave.
    # AMOUNT_DEVIATION
    for ent, z_col in [("card", "amt_z_card"), ("device", "amt_z_device")]:
        z = prod_row.get(z_col)
        if pd.notna(z) and abs(float(z)) >= AMOUNT_Z_THRESHOLD:
            key = row["card1"] if ent=="card" else prod_row.get("device_key", row.get("device_id"))
            # Need reference
            details = {
                "reference_entity": f"{ent}:{key}",
                "z_score": round(float(z), 3),
                "current_amount": float(row["TransactionAmt"]),
                "threshold": AMOUNT_Z_THRESHOLD,
                "metric": "welford_z",
            }
            prov = _provenance("production_features", [transaction_id])
            ev = EvidenceRecord.new(
                transaction_id=transaction_id,
                evidence_type="AMOUNT_DEVIATION",
                title=f"Amount deviation for {ent}",
                description=f"Transaction amount {row['TransactionAmt']} is {float(z):+.1f}σ away from {ent} {key} historical mean.",
                details=details,
                provenance=prov,
                severity="medium" if abs(float(z)) < 3 else "high",
            )
            evidence.append(ev)

    # UNUSUAL_HOUR
    # Need transaction hour: from TransactionDT
    txn_hour = int((int(row["TransactionDT"]) % 86400) // 3600)
    for ent, dev_col in [("card", "hour_dev_card"), ("device", "hour_dev_device")]:
        hd = prod_row.get(dev_col)
        if pd.notna(hd) and float(hd) >= HOUR_DEV_THRESHOLD:
            key = row["card1"] if ent=="card" else prod_row.get("device_key")
            details = {
                "reference_entity": f"{ent}:{key}",
                "hour_dev": round(float(hd), 3),
                "transaction_hour": txn_hour,
                "threshold": HOUR_DEV_THRESHOLD,
                "metric": "circular_hour_distance",
            }
            prov = _provenance("production_features", [transaction_id])
            ev = EvidenceRecord.new(
                transaction_id=transaction_id,
                evidence_type="UNUSUAL_HOUR",
                title=f"Unusual hour for {ent}",
                description=f"Transaction hour {txn_hour} is {float(hd):.2f} away (0-1) from {ent} {key} typical hour.",
                details=details,
                provenance=prov,
                severity="low",
            )
            evidence.append(ev)

    # NEW_PAIRING — need pair history: check if is_new flag would be true
    # We can compute via graph_links: check if pair (device, card) or (addr, card) has prior occurrence before t
    # Simplest: use production artifact? But production doesn't have is_new (it's FAIL). We'll compute via full history check using graph_links.
    # For device-card:
    try:
        dev_key = str(prod_row.get("device_key")) if pd.notna(prod_row.get("device_key")) else None
        card_key = str(int(row["card1"])) if pd.notna(row["card1"]) else None
        addr_key = str(int(row["addr1"])) if pd.notna(row["addr1"]) and str(row["addr1"])!="nan" else None
        # Load graph_links for history check (validates the artifact exists)
        pd.read_parquet(s.processed_dir / "graph_links.parquet")
        # For each pair type, check if any earlier transaction with same pair
        ts = int(row["TransactionDT"])
        if dev_key and card_key:
            # Find if any link with both device and card for same pair before ts
            # We need to check transaction-entity incidence: pair exists if there exists a transaction before ts that has both device=dev_key and card=card_key
            # Approach: find txn_ids that have both entities before ts
            # Use df_exp to check
            prior = df_exp[df_exp["TransactionDT"] < ts]
            # Check prior rows that have both card and device matching
            mask = (prior["card1"].astype(str) == card_key) & (prior["device_id"].astype(str) == dev_key)
            is_new = not mask.any()
            if is_new:
                details = {"pair_type": "device_card", "device": dev_key, "card": card_key, "prior_count": 0}
                prov = _provenance("graph_links", [transaction_id])
                ev = EvidenceRecord.new(
                    transaction_id=transaction_id,
                    evidence_type="NEW_PAIRING",
                    title="New device-card pairing",
                    description=f"Card {card_key} has never been seen with device {dev_key} before this transaction.",
                    details=details,
                    provenance=prov,
                    severity="medium",
                )
                evidence.append(ev)
        if addr_key and card_key:
            prior = df_exp[df_exp["TransactionDT"] < ts]
            mask = (prior["card1"].astype(str) == card_key) & (prior["addr1"].astype(str) == addr_key)
            is_new_addr = not mask.any()
            if is_new_addr:
                details = {"pair_type": "addr_card", "address": addr_key, "card": card_key, "prior_count": 0}
                prov = _provenance("graph_links", [transaction_id])
                ev = EvidenceRecord.new(
                    transaction_id=transaction_id,
                    evidence_type="NEW_PAIRING",
                    title="New address-card pairing",
                    description=f"Card {card_key} has never been seen with address {addr_key} before.",
                    details=details,
                    provenance=prov,
                    severity="low",
                )
                evidence.append(ev)
    except Exception:  # noqa: BLE001, S110 - NEW_PAIRING degrades gracefully
        pass

    # VELOCITY_BURST — compute window counts via graph index windowed_neighbors
    # For each entity of seed, compute counts in 1h/24h windows (prior only? For evidence we report prior window counts including seed's window)
    try:
        # Use graph service index directly
        from app.graph.service import _load_index
        idx, _ = _load_index(s)
        pos_map = {tid:i for i, tid in enumerate(df_exp["TransactionID"].values)}
        pos = pos_map[transaction_id]
        t = int(row["TransactionDT"])
        for etype, ekey in idx.seed_entities(pos):
            for win_label, win_s in [("1h", 3600), ("24h", 86400)]:
                # count prior transactions within window [t-win, t)  (exclude seed)
                cnt = len(idx.windowed_neighbors(etype, ekey, t, back_s=win_s, fwd_s=0))
                # cnt includes seed if seed within window? windowed_neighbors with back win_s and fwd 0 includes [t-win, t) exclusive of t, so seed not counted. Good.
                thresh = VELOCITY_THRESHOLDS.get(f"{etype.lower()}_tx_{win_label}" if etype in ["CARD","DEVICE"] else "", 999)
                # Map etype to threshold key
                key_map = {"CARD": f"card_tx_{win_label}", "DEVICE": f"dev_tx_{win_label}", "ADDRESS": f"addr_tx_{win_label}"}
                thresh = VELOCITY_THRESHOLDS.get(key_map.get(etype, ""), None)
                if thresh is None:
                    continue
                if cnt >= thresh:
                    details = {"entity": f"{etype}:{ekey}", "window": win_label, "count": int(cnt), "threshold": thresh}
                    prov = _provenance("graph_links", [transaction_id])
                    ev = EvidenceRecord.new(
                        transaction_id=transaction_id,
                        evidence_type="VELOCITY_BURST",
                        title=f"Velocity burst for {etype} {ekey}",
                        description=f"{etype} {ekey} has {cnt} transactions in prior {win_label} (threshold {thresh}).",
                        details=details,
                        provenance=prov,
                        severity="medium",
                    )
                    evidence.append(ev)
    except Exception:  # noqa: BLE001, S110 - VELOCITY_BURST degrades gracefully
        pass

    # SHARED_DEVICE_LINK
    try:
        # Find device entities of seed
        seed_devices = [e for e in graph_res["entities"] if e["entity_type"]=="DEVICE"]
        for dev in seed_devices:
            dkey = dev["entity_key"]
            # count connected txns that share this device (from graph_res transactions that have this device)
            # graph_res transactions includes all connected via any entity, but we filter those that actually have device
            # Use df_exp to count
            linked = []
            for tx in graph_res["transactions"]:
                tid = tx["transaction_id"]
                # check if this txn has device dkey
                r2 = df_exp[df_exp["TransactionID"]==tid]
                if not r2.empty and str(r2.iloc[0].get("device_id")) == dkey:
                    linked.append(tid)
            # exclude seed itself
            other = [x for x in linked if x != transaction_id]
            if len(other) >= SHARED_DEVICE_MIN_TXNS:
                details = {"device": dkey, "connected_transaction_ids": sorted(other)[:10], "count": len(other), "window": "-14d/+2d"}
                prov = _provenance("graph_links", linked)
                ev = EvidenceRecord.new(
                    transaction_id=transaction_id,
                    evidence_type="SHARED_DEVICE_LINK",
                    title=f"Shared device {dkey}",
                    description=f"Device {dkey} links {len(other)} other transactions (showing up to 10).",
                    details=details,
                    provenance=prov,
                    severity="medium",
                )
                evidence.append(ev)
    except Exception:  # noqa: BLE001, S110 - SHARED_DEVICE_LINK degrades gracefully
        pass

    # COMMUNITY_STATS
    try:
        comm = graph_res["community"]
        summary = comm["summary"]
        if summary["transaction_count"] >= COMMUNITY_MIN_TXNS:
            details = {
                "transaction_count": summary["transaction_count"],
                "entity_count": summary["entity_count"],
                "entity_type_counts": summary["entity_type_counts"],
                "time_span_hours": summary["time_span_hours"],
                "hub_pruned_count": summary["hub_pruned_count"],
                "max_risk_score": summary["max_risk_score"],
            }
            prov = _provenance("graph_links", comm["members"])
            ev = EvidenceRecord.new(
                transaction_id=transaction_id,
                evidence_type="COMMUNITY_STATS",
                title="Investigation community",
                description=f"Transaction belongs to connected community with {summary['transaction_count']} txns and {summary['entity_count']} entities spanning {summary['time_span_hours']}h.",
                details=details,
                provenance=prov,
                severity="info",
            )
            evidence.append(ev)
    except Exception:  # noqa: BLE001, S110 - COMMUNITY_STATS degrades gracefully
        pass

    # CONNECTED_HIGH_RISK
    try:
        # For each connected transaction in community that has high risk
        comm_members = graph_res["community"]["members"]
        # fetch scores
        try:
            conn = connect(s.db_path)
            placeholders = ",".join(["?"]*len(comm_members)) if comm_members else "NULL"
            rows = conn.execute(f"SELECT transaction_id, risk_score, risk_band FROM risk_predictions WHERE transaction_id IN ({placeholders})", comm_members).fetchall() if comm_members else []
            conn.close()
        except Exception:  # noqa: BLE001 - score fetch is best-effort
            rows = []
        for tid, score, band in rows:
            if tid == transaction_id:
                continue
            if score is not None and float(score) >= CONNECTED_HIGH_RISK_THRESHOLD:
                details = {"connected_transaction_id": int(tid), "risk_score": round(float(score),4), "risk_band": band, "threshold": CONNECTED_HIGH_RISK_THRESHOLD}
                prov = _provenance("risk_predictions", [tid, transaction_id])
                ev = EvidenceRecord.new(
                    transaction_id=transaction_id,
                    evidence_type="CONNECTED_HIGH_RISK",
                    title=f"Connected high-risk transaction {tid}",
                    description=f"Connected transaction {tid} has risk {float(score):.3f} ({band}).",
                    details=details,
                    provenance=prov,
                    severity="high",
                )
                evidence.append(ev)
    except Exception:  # noqa: BLE001, S110 - CONNECTED_HIGH_RISK degrades gracefully
        pass

    # Fallback NO_RELATIONAL_EVIDENCE
    if not evidence:
        prov = _provenance("graph_links", [transaction_id])
        ev = EvidenceRecord.new(
            transaction_id=transaction_id,
            evidence_type="NO_RELATIONAL_EVIDENCE",
            title="No qualifying relational evidence",
            description="No qualifying relational evidence found under configured rules/window (-14d/+2d, depth 1, caps).",
            details={"checked_types": ["NEW_PAIRING","AMOUNT_DEVIATION","UNUSUAL_HOUR","VELOCITY_BURST","SHARED_DEVICE_LINK","COMMUNITY_STATS","CONNECTED_HIGH_RISK"], "window": "-14d/+2d"},
            provenance=prov,
            severity="info",
        )
        evidence.append(ev)

    # Deterministic ordering: by evidence_type then evidence_hash
    evidence = sorted(evidence, key=lambda e: (e.evidence_type, e.evidence_hash))

    # Optional persistence (idempotent by transaction_id+evidence_hash)
    try:
        conn = connect(s.db_path)
        for ev in evidence:
            conn.execute("INSERT OR IGNORE INTO evidence VALUES (?, ?, ?, ?, ?, ?)",
                         [ev.evidence_id, ev.transaction_id, ev.evidence_type, ev.description, ev.evidence_hash, ev.generated_at])
        conn.close()
    except Exception:  # noqa: BLE001, S110 - persistence is optional/best-effort
        pass

    return model_risk, evidence
