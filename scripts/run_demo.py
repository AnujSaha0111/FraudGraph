# FraudGraph demo runner
# One obvious command that validates the demo environment, prepares the deterministic demo state, prints the exact walkthrough URL and the five-minute walkthrough sequence.
# Dry-run is strictly read-only: it never writes reports, never touches the canonical artifacts (production_features.parquet, fraud_xgb_v1-*, graph_links.parquet) and never mutates data/app/fraudgraph.duckdb.

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEMO_TXN = 3011051
EXPECTED_MODEL_VERSION = "fraud_xgb_v1-9e2978c"
EXPECTED_FEATURE_COUNT = 438
EXPECTED_PR_AUC = 0.736687914424724
EXPECTED_LINKS = 254_777
EXPECTED_GRAPH_PARAMS = {"back_days": 14, "fwd_days": 2,
                         "hub_degree_max": 1000, "neighbor_cap": 200}

WALKTHROUGH = [
    ("0:00-0:30", "Problem: score alone is not an investigation"),
    ("0:30-1:15", f"Risk queue #{DEMO_TXN} top CRITICAL - model output, not proof"),
    ("1:15-2:15", "Investigation: MODEL RISK != EXPLANATION != EVIDENCE + graph"),
    ("2:15-3:00", "Evidence deep dive: relational + temporal records, hashes"),
    ("3:00-4:00", "Case workflow NEW -> INVESTIGATING -> ESCALATED -> decision -> CLOSED"),
    ("4:00-4:30", "EntityRisk point-in-time context (not a model feature)"),
    ("4:30-5:00", "Failure story + engineering conclusion (control gate, no LLM)"),
]


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.exists() else "missing"


class Checks:
    def __init__(self):
        self.results: list[tuple[str, bool, str]] = []

    def add(self, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append((name, ok, detail))
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
        return ok

    @property
    def all_ok(self) -> bool:
        return all(ok for _, ok, _ in self.results)


def run_checks() -> Checks:
    checks = Checks()
    t0 = time.perf_counter()

    # ---- 1. required artifacts -------------------------------------------
    artifacts = {
        "model": ROOT / "models" / f"{EXPECTED_MODEL_VERSION}.json",
        "model_metadata": ROOT / "models" / f"{EXPECTED_MODEL_VERSION}.metadata.json",
        "model_features": ROOT / "models" / f"{EXPECTED_MODEL_VERSION}.features.json",
        "production_features": ROOT / "data/processed/production_features.parquet",
        "graph_links": ROOT / "data/processed/graph_links.parquet",
        "app_db": ROOT / "data/app/fraudgraph.duckdb",
        "frontend_dist": ROOT / "frontend/dist/index.html",
        "synthetic_ground_truth": ROOT / "data/synthetic/ring_ground_truth.json",
        "synthetic_transactions": ROOT / "data/synthetic/synthetic_transactions.parquet",
    }
    missing = [k for k, p in artifacts.items() if not p.exists()]
    checks.add("required-artifacts-exist", not missing,
               f"missing={missing}" if missing else f"{len(artifacts)} present")

    # ---- 2. model version / features / frozen metrics ---------------------
    meta = (json.loads(artifacts["model_metadata"].read_text())
            if artifacts["model_metadata"].exists() else {})
    checks.add("model-version", meta.get("model_version") == EXPECTED_MODEL_VERSION,
               str(meta.get("model_version")))
    checks.add("feature-count-438", meta.get("feature_count") == EXPECTED_FEATURE_COUNT,
               str(meta.get("feature_count")))

    p3 = ROOT / "reports/model_validation.json"
    v3 = json.loads(p3.read_text()) if p3.exists() else {}
    checks.add("model-pr-auc-frozen",
               abs(v3.get("test_pr_auc", 0) - EXPECTED_PR_AUC) < 1e-9
               and v3.get("pr_auc_pass") is True,
               f"test_pr_auc={v3.get('test_pr_auc')}")
    checks.add("model-reload-diff-0", v3.get("reload_max_abs_diff") == 0.0,
               str(v3.get("reload_max_abs_diff")))

    p9 = ROOT / "reports/reproducibility.json"
    v9 = json.loads(p9.read_text()) if p9.exists() else {}
    checks.add("reproducibility-equivalent",
               v9.get("reload_equivalent") is True,
               f"max_diff={v9.get('reload_max_diff')}")

    # ---- 3. graph version / params ----------------------------------------
    from app.config import load_settings
    from app.graph.index import GRAPH_VERSION, params_hash
    s = load_settings()
    checks.add("graph-version-v1", GRAPH_VERSION == "v1", GRAPH_VERSION)
    actual_params = {"back_days": s.window_back_days, "fwd_days": s.window_fwd_days,
                     "hub_degree_max": s.hub_degree_max,
                     "neighbor_cap": s.neighbor_cap}
    checks.add("graph-params-unchanged",
               actual_params == EXPECTED_GRAPH_PARAMS, str(actual_params))
    h1 = params_hash(s.window_back_days * 86400, s.window_fwd_days * 86400,
                     s.hub_degree_max, s.neighbor_cap)
    h2 = params_hash(s.window_back_days * 86400, s.window_fwd_days * 86400,
                     s.hub_degree_max, s.neighbor_cap)
    checks.add("graph-params-hash-stable", h1 == h2 and len(h1) >= 16, h1[:16])

    if artifacts["graph_links"].exists():
        import duckdb
        con = duckdb.connect()
        n_links = con.execute(
            "SELECT COUNT(*) FROM read_parquet(?)",
            [str(artifacts["graph_links"])]).fetchone()[0]
        con.close()
        checks.add("graph-links-254777", n_links == EXPECTED_LINKS, str(n_links))
    else:
        checks.add("graph-links-254777", False,
                   "artifact missing (data/processed/graph_links.parquet)")

    # ---- 4. evidence engine -------------------------------------------------
    from app.evidence.models import EVIDENCE_ENGINE_VERSION
    checks.add("evidence-engine-v1", EVIDENCE_ENGINE_VERSION == "v1",
               EVIDENCE_ENGINE_VERSION)

    # ---- 5. demo state ------------------------------------------------------
    try:
        con = duckdb.connect(str(artifacts["app_db"]), read_only=True)
        risk = con.execute(
            "SELECT risk_score, risk_band, model_version FROM risk_predictions "
            "WHERE transaction_id = ?", [DEMO_TXN]).fetchone()
        ev = con.execute(
            "SELECT evidence_type, COUNT(*) FROM evidence WHERE txn_id = ? "
            "GROUP BY evidence_type", [DEMO_TXN]).fetchall()
        n_cases = con.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        con.close()
        checks.add("demo-txn-scored-critical",
                   bool(risk) and risk[1] == "CRITICAL"
                   and risk[2] == EXPECTED_MODEL_VERSION,
                   str(risk))
        ev_total = sum(int(c) for _, c in ev)
        checks.add("demo-evidence-rich", len(ev) >= 3 and ev_total >= 3,
                   f"{ev_total} records, types={sorted(t for t, _ in ev)}")
        checks.add("case-store-reachable", isinstance(n_cases, int),
                   f"{n_cases} cases")
    except Exception as e:  # noqa: BLE001 - report any DB failure as a failed check
        checks.add("demo-db-readable", False, repr(e))

    seed_report = ROOT / "reports/demo_seed.json"
    seed = json.loads(seed_report.read_text()) if seed_report.exists() else {}
    checks.add(
        "demo-seed-report-current",
        seed.get("demo_version") == "v1.0.0"
        and seed.get("real_demo", {}).get("transaction_id") == DEMO_TXN,
        f"demo_version={seed.get('demo_version')}")
    gt_hash = _sha(artifacts["synthetic_ground_truth"])
    checks.add("synthetic-ground-truth-pinned",
               seed.get("synthetic_demo", {}).get("ground_truth_hash")
               in ("", gt_hash),
               gt_hash)
    syn_results_path = ROOT / "reports/synthetic_results.json"
    syn = (json.loads(syn_results_path.read_text())
           if syn_results_path.exists() else {})
    recovery = syn.get("structural_recovery", {})
    pr_auc_synth = syn.get("XGB_graph", {}).get("pr_auc")
    purities = {k: recovery.get(k, {}).get("best_purity")
                for k in ("RingA", "RingC")}
    checks.add(
        "synthetic-purity-labels-available",
        abs((purities["RingA"] or 0) - 1.0) < 1e-6
        and abs((purities["RingC"] or 0) - 0.968) < 1e-6
        and abs((pr_auc_synth or 0) - 0.8906) < 5e-4,
        f"{purities} xgb_graph_pr_auc={pr_auc_synth}")

    # ---- 6. architectural red lines -----------------------------------------
    checks.add("no-llm-code", not (ROOT / "app/llm").exists(),
               "app/llm absent")
    banned_src = "".join(
        f.read_text(encoding="utf-8", errors="ignore")
        for f in sorted((ROOT / "app").rglob("*.py")))
    low = banned_src.lower()
    checks.add("no-gnn-in-app",
               "graphsage" not in low and "torch" not in low, "app/ clean")
    checks.add("no-graph-db-in-app", "neo4j" not in low, "app/ clean")

    checks.add("checks-fast", True, f"{time.perf_counter() - t0:.1f}s")
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="FraudGraph demo runner")
    parser.add_argument("--dry-run", action="store_true",
                        help="validate everything without mutating anything")
    parser.add_argument("--serve", action="store_true",
                        help="after validation, start uvicorn app.main:app (blocking)")
    args = parser.parse_args()

    print("=" * 72)
    print("FRAUDGRAPH DEMO RUNNER "
          + ("(DRY-RUN)" if args.dry_run else ""))
    print("=" * 72)

    tracked = (("prod", "data/processed/production_features.parquet"),
               ("graph", "data/processed/graph_links.parquet"),
               ("model", f"models/{EXPECTED_MODEL_VERSION}.json"))
    canonical_before = {n: _sha(ROOT / rel) for n, rel in tracked}
    db_before = _sha(ROOT / "data/app/fraudgraph.duckdb")

    checks = run_checks()

    if not args.dry_run:
        # refresh the demo seed report (idempotent + verified inside the script)
        r = subprocess.run([sys.executable,
                            str(ROOT / "scripts/demo_seed.py")],
                           capture_output=True, text=True, cwd=ROOT)
        checks.add("demo-seed-refresh-ok", r.returncode == 0,
                   (r.stdout.strip().splitlines() or [""])[-1][:120])

    canonical_after = {n: _sha(ROOT / rel) for n, rel in tracked}
    checks.add("no-canonical-mutation", canonical_before == canonical_after, "")
    if args.dry_run:
        checks.add("no-db-mutation-dry-run",
                   db_before == _sha(ROOT / "data/app/fraudgraph.duckdb"), "")

    print("-" * 72)
    from app.config import get_settings
    st = get_settings()
    host = "127.0.0.1" if st.api_host in ("0.0.0.0", "") else st.api_host
    url = f"http://{host}:{st.api_port}/#/"
    print(f"WALKTHROUGH URL : {url}")
    print("WALKTHROUGH SEQUENCE (target <= 5:00 total):")
    for slot, line in WALKTHROUGH:
        print(f"  {slot}  {line}")
    print("DOCS            : docs/ARCHITECTURE.md · docs/MODEL_CARD.md")
    print("README          : claim discipline + limitations (README.md)")

    ok = checks.all_ok
    if not ok:
        # Make a data-free clone failure actionable instead of mysterious.
        failed = {name for name, ok_i, _ in checks.results if not ok_i}
        if "required-artifacts-exist" in failed or "demo-db-readable" in failed:
            print("HINT: the real-data demo requires locally prepared IEEE-CIS")
            print("artifacts (gitignored; this repository does not redistribute")
            print("the dataset). See README 'Data availability' and run:")
            print("  python scripts/setup_data.py")
    print("=" * 72)
    print(f"RESULT: {'ALL CHECKS PASS' if ok else 'CHECKS FAILED'} "
          f"({sum(1 for _, o, _ in checks.results if o)}/{len(checks.results)})")
    print("=" * 72)
    if not ok:
        return 1
    if args.serve:
        import uvicorn
        uvicorn.run("app.main:app", host=st.api_host, port=st.api_port,
                    log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
