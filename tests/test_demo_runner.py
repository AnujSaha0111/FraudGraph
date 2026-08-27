# Demo runner dry-run tests.
# The dry-run must validate the full demo environment without mutating any canonical artifact or the app database.

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

CANONICAL = [
    "data/processed/production_features.parquet",
    "data/processed/graph_links.parquet",
    "models/fraud_xgb_v1-9e2978c.json",
    "models/fraud_xgb_v1-9e2978c.metadata.json",
]


def _digests():
    return {
        p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
        for p in CANONICAL if Path(p).exists()
    }


@pytest.mark.real_data
def test_demo_dry_run_passes_and_mutates_nothing():
    before = _digests()
    r = subprocess.run(
        [sys.executable, "scripts/run_demo.py", "--dry-run"],
        capture_output=True, text=True, timeout=180, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ALL CHECKS PASS" in r.stdout
    assert "no-canonical-mutation" in r.stdout
    assert "no-db-mutation-dry-run" in r.stdout
    assert _digests() == before


@pytest.mark.real_data
def test_demo_dry_run_prints_walkthrough_contract():
    r = subprocess.run(
        [sys.executable, "scripts/run_demo.py", "--dry-run"],
        capture_output=True, text=True, timeout=180, check=False)
    out = r.stdout
    assert "http://127.0.0.1:8000/#/" in out
    for token in ("Risk queue", "Investigation", "Evidence deep dive",
                  "Case workflow", "EntityRisk", "Failure story"):
        assert token in out, f"walkthrough step missing: {token}"
    # red lines verified as part of every dry run
    for check in ("model-pr-auc-frozen", "feature-count-438",
                  "graph-links-254777", "evidence-engine-v1",
                  "no-llm-code", "no-gnn-in-app"):
        line = next(l for l in out.splitlines() if l.strip().startswith(f"PASS  {check}"))
        assert line.startswith("PASS"), line


@pytest.mark.real_data
def test_demo_seed_report_consistent_with_runner_expectations():
    seed = json.loads(Path("reports/demo_seed.json").read_text())
    assert seed["demo_version"] == "v1.0.0"
    assert seed["real_demo"]["transaction_id"] == 3011051
    assert seed["real_demo"]["model_version"] == "fraud_xgb_v1-9e2978c"
    assert seed["real_demo"]["evidence_total"] >= 3
    assert "Synthetic structural validation" in seed["synthetic_demo"]["label"]
