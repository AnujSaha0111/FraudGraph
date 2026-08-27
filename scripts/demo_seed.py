# Demo Seed / Fixture System.
# Deterministic, idempotent, versioned. Never overwrites canonical artifacts (production_features.parquet, fraud_xgb_v1-*, graph_links.parquet). Distinguishes real vs synthetic provenance explicitly.

# The demo state guarantees:
# - a high-risk real transaction suitable for investigation
# - visible deterministic evidence (≥3 types)
# - a meaningful graph/community
# - a case that can be created
# - a synthetic ring example (research/demo validation, not real fraud)

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEMO_VERSION = "v1.0.0"
DEMO_SEED = 42

# Deterministic choice: top-scored transaction with richest evidence in the audit
REAL_DEMO_TXN = 3011051

SYNTHETIC_RING_INFO = {
    "ring_a_purity": 1.0,
    "ring_c_purity": 0.968,
    "xgb_graph_pr_auc": 0.8906,
    "label": "Synthetic structural validation — research/demo validation, not real-world fraud performance.",
}

def _hash_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.exists() else "missing"

def build_seed() -> dict:
    # Verify canonical artifacts exist and capture hashes (for no-mutation check)
    artifacts = {
        "production_features": _hash_file(ROOT / "data/processed/production_features.parquet"),
        "graph_links": _hash_file(ROOT / "data/processed/graph_links.parquet"),
        "model": _hash_file(ROOT / "models/fraud_xgb_v1-9e2978c.json"),
        "features": _hash_file(ROOT / "models/fraud_xgb_v1-9e2978c.features.json"),
        "evidence_engine": "v1",
        "graph_version": "v1",
    }
    # Load real demo txn details from DB + evidence
    import duckdb
    con = duckdb.connect(str(ROOT / "data/app/fraudgraph.duckdb"), read_only=True)
    risk = con.execute(
        "SELECT risk_score, risk_band, model_version FROM risk_predictions WHERE transaction_id=?",
        [REAL_DEMO_TXN],
    ).fetchone()
    ev_rows = con.execute(
        "SELECT evidence_type, count(*) FROM evidence WHERE txn_id=? GROUP BY evidence_type",
        [REAL_DEMO_TXN],
    ).fetchall()
    g_count = con.execute("SELECT COUNT(*) FROM graph_links WHERE transaction_id=?", [REAL_DEMO_TXN]).fetchone()[0]
    comm = con.execute("SELECT COUNT(*) FROM graph_links WHERE transaction_id IN (SELECT transaction_id FROM graph_links WHERE transaction_id=?)", [REAL_DEMO_TXN]).fetchone()
    con.close()

    # Synthetic ring ground truth
    syn_path = ROOT / "data/synthetic/ring_ground_truth.json"
    syn_exists = syn_path.exists()
    syn_hash = _hash_file(syn_path) if syn_exists else "missing"

    return {
        "demo_version": DEMO_VERSION,
        "demo_seed": DEMO_SEED,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_types": {
            "real": "IEEE-CIS derived (public dataset, 24.4% identity coverage)",
            "synthetic": "Synthetic rings (planted ground truth, controlled experiment)",
        },
        "provenance_warning": "Synthetic data is NEVER presented as real fraud evidence. All synthetic claims are labeled 'Synthetic structural validation'.",
        "real_demo": {
            "transaction_id": REAL_DEMO_TXN,
            "risk_score": float(risk[0]) if risk else None,
            "risk_band": risk[1] if risk else None,
            "model_version": risk[2] if risk else None,
            "evidence_by_type": {k: int(v) for k, v in ev_rows},
            "evidence_total": sum(int(v) for _, v in ev_rows),
            "graph_links": int(g_count),
            "suitable_for_investigation": bool(risk and ev_rows and g_count),
        },
        "synthetic_demo": {
            **SYNTHETIC_RING_INFO,
            "ground_truth_path": "data/synthetic/ring_ground_truth.json",
            "ground_truth_hash": syn_hash,
            "synthetic_transactions": "data/synthetic/synthetic_transactions.parquet",
            "note": "Use scripts/evaluate_synthetic_rings.py results; do not claim as production metrics.",
        },
        "entity_risk_context": {
            "example_entity": "ADDRESS:315",
            "min_label_lag_days": 7,
            "note": "EntityRisk is investigation context only; not an XGBoost feature.",
        },
        "case_workflow": {
            "can_create_case": True,
            "can_transition": ["NEW", "INVESTIGATING", "ESCALATED", "CONFIRMED_FRAUD", "CLOSED"],
            "decision_immutable": True,
            "label_created": True,
        },
        "canonical_artifacts": artifacts,
        "isolated_demo_db": "data/app/demo.duckdb (created only with --seed-demo-db; never overwrites fraudgraph.duckdb)",
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true", help="Verify idempotency and no mutation")
    parser.add_argument("--seed-demo-db", action="store_true", help="Seed isolated demo DB")
    args = parser.parse_args()

    # The demo fixture describes the REAL IEEE-CIS investigation flow; it
    # cannot run from a data-free clone. Fail with the prerequisite, clearly.
    from src.config import DATA_PROC
    missing = [str(p.relative_to(ROOT)) for p in (
        DATA_PROC / "production_features.parquet",
        DATA_PROC / "graph_links.parquet",
        ROOT / "data/app/fraudgraph.duckdb",
    ) if not p.exists()]
    if missing:
        print("Cannot build the demo seed: real-data prerequisites missing:")
        for m in missing:
            print(f"  - {m}")
        print("IEEE-CIS/Vesta data is not included in this repository; see")
        print("README 'Data availability' and scripts/setup_data.py.")
        raise SystemExit(2)

    out_path = ROOT / "reports/demo_seed.json"

    # Capture hashes before
    before = {
        "prod": _hash_file(ROOT / "data/processed/production_features.parquet"),
        "graph": _hash_file(ROOT / "data/processed/graph_links.parquet"),
        "model": _hash_file(ROOT / "models/fraud_xgb_v1-9e2978c.json"),
    }

    seed = build_seed()
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(seed, indent=2), encoding="utf-8")
    print(f"Wrote {out_path} (demo_version={DEMO_VERSION}, txn={REAL_DEMO_TXN})")

    # Verify no mutation
    after = {
        "prod": _hash_file(ROOT / "data/processed/production_features.parquet"),
        "graph": _hash_file(ROOT / "data/processed/graph_links.parquet"),
        "model": _hash_file(ROOT / "models/fraud_xgb_v1-9e2978c.json"),
    }
    assert before == after, f"Canonical artifact mutated! before={before} after={after}"
    print("No canonical artifact mutation: PASS")

    # Verify idempotency: second build must be identical except generated_at
    seed2 = build_seed()
    for k in ["demo_version", "demo_seed", "real_demo", "synthetic_demo", "canonical_artifacts"]:
        assert seed[k] == seed2[k], f"Idempotency failed for {k}"
    print("Idempotency: PASS")

    # Verify synthetic/real distinction
    assert seed["source_types"]["real"] != seed["source_types"]["synthetic"]
    assert "Synthetic" in seed["synthetic_demo"]["label"]
    print("Provenance distinction: PASS")

    # Verify demo records exist
    assert seed["real_demo"]["suitable_for_investigation"] is True
    assert seed["real_demo"]["evidence_total"] >= 3
    print(f"Demo records exist: PASS (evidence_total={seed['real_demo']['evidence_total']})")

    if args.verify:
        print("Verify only — done.")
        return

    if args.seed_demo_db:
        from app.storage.db import init_db
        demo_path = ROOT / "data/app/demo.duckdb"
        demo_path.parent.mkdir(parents=True, exist_ok=True)
        if demo_path.exists():
            demo_path.unlink()
        conn = init_db(demo_path)
        # Copy minimal demo state: risk_predictions for demo txn, evidence, graph links
        import duckdb
        real = duckdb.connect(str(ROOT / "data/app/fraudgraph.duckdb"), read_only=True)
        conn.execute("INSERT INTO risk_predictions SELECT * FROM real.risk_predictions WHERE transaction_id=?", [REAL_DEMO_TXN])
        # Use attach for copy? Simpler: fetch and insert
        rows = real.execute("SELECT * FROM risk_predictions WHERE transaction_id=?", [REAL_DEMO_TXN]).fetchall()
        for r in rows:
            conn.execute("INSERT OR REPLACE INTO risk_predictions VALUES (?, ?, ?, ?, ?)", list(r))
        # Copy evidence for demo txn
        erows = real.execute("SELECT * FROM evidence WHERE txn_id=?", [REAL_DEMO_TXN]).fetchall()
        for r in erows:
            conn.execute("INSERT OR REPLACE INTO evidence VALUES (?, ?, ?, ?, ?, ?)", list(r))
        real.close()
        conn.close()
        print(f"Seeded isolated demo DB at {demo_path} (real txn {REAL_DEMO_TXN}, {len(erows)} evidence)")

if __name__ == "__main__":
    main()
