import json
from pathlib import Path

import pytest


@pytest.mark.real_data
def test_demo_seed_deterministic():
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "scripts/demo_seed.py", "--verify"], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    j = json.loads(Path("reports/demo_seed.json").read_text())
    assert j["demo_version"] == "v1.0.0"
    assert j["demo_seed"] == 42
    assert j["real_demo"]["transaction_id"] == 3011051
    assert j["real_demo"]["evidence_total"] >= 3

@pytest.mark.real_data
def test_demo_seed_no_canonical_mutation():
    import hashlib
    p = Path("data/processed/production_features.parquet")
    before = hashlib.sha256(p.read_bytes()).hexdigest()
    import subprocess
    import sys
    subprocess.run([sys.executable, "scripts/demo_seed.py"], check=True)
    after = hashlib.sha256(p.read_bytes()).hexdigest()
    assert before == after

@pytest.mark.real_data
def test_synthetic_real_distinction():
    j = json.loads(Path("reports/demo_seed.json").read_text())
    assert j["source_types"]["real"] != j["source_types"]["synthetic"]
    assert "Synthetic" in j["synthetic_demo"]["label"]
    assert j["provenance_warning"].startswith("Synthetic data is NEVER")

@pytest.mark.real_data
def test_demo_seed_reports_exist():
    j = json.loads(Path("reports/demo_seed.json").read_text())
    assert j["real_demo"]["suitable_for_investigation"] is True
    assert j["synthetic_demo"]["ring_a_purity"] == 1.0
