# Isolation hardening
# Ensures future runs cannot accidentally reuse developer-local state:
# existing DB, dist, node_modules, venv, or generated caches.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_settings


def test_settings_respects_fg_db_path(tmp_path):
    # FG_DB_PATH must isolate DB — two different paths must not share state
    s1 = load_settings(environ={"FG_BASE_DIR": str(tmp_path), "FG_DB_PATH": str(tmp_path / "a.duckdb")})
    s2 = load_settings(environ={"FG_BASE_DIR": str(tmp_path), "FG_DB_PATH": str(tmp_path / "b.duckdb")})
    assert s1.db_path != s2.db_path
    assert s1.db_path == tmp_path / "a.duckdb"
    # No hardcoded absolute path in config
    assert "D:/FraudGraph" not in str(s1.db_path)


def test_frontend_dist_is_settings_driven(tmp_path):
    # Frontend dist must come from settings, not a hardcoded path
    s = load_settings(environ={"FG_BASE_DIR": str(tmp_path), "FG_DB_PATH": str(tmp_path / "x.duckdb")})
    assert s.frontend_dist_dir == tmp_path / "frontend" / "dist"
    # App must not hardcode frontend path
    src = Path("app/main.py").read_text()
    assert "frontend_dist_dir" in src
    assert "D:/FraudGraph/frontend/dist" not in src


def test_no_hardcoded_db_path_in_storage():
    # Storage layer must not hardcode the production DB path
    src = Path("app/storage/db.py").read_text()
    # The only place production path appears is in config defaults, not storage
    assert "fraudgraph.duckdb" not in src


def test_isolated_db_does_not_leak(tmp_path):
    # Two TestClients with different FG_DB_PATH must have isolated case tables.
    from fastapi.testclient import TestClient

    from app.config import load_settings
    from app.main import create_app

    s_a = load_settings(environ={"FG_BASE_DIR": str(tmp_path), "FG_DB_PATH": str(tmp_path / "iso_a.duckdb")})
    s_b = load_settings(environ={"FG_BASE_DIR": str(tmp_path), "FG_DB_PATH": str(tmp_path / "iso_b.duckdb")})

    # Init both DBs
    from app.storage.db import init_db
    init_db(s_a.db_path)
    init_db(s_b.db_path)

    # Seed only A
    from app.storage.db import connect
    conn_a = connect(s_a.db_path)
    conn_a.execute("INSERT OR REPLACE INTO risk_predictions VALUES (?, ?, ?, ?, NULL)", [999991, "fraud_xgb_v1-9e2978c", 0.9, "CRITICAL"])
    conn_a.execute("INSERT OR REPLACE INTO evidence VALUES (?, ?, 'NEW_PAIRING', '{}', 'h', NULL)", ["ev-iso-1", 999991])
    conn_a.close()

    c_a = TestClient(create_app(s_a))
    c_b = TestClient(create_app(s_b))

    # A should have a case after creation, B should have empty queue
    r = c_a.post("/cases", json={"transaction_id": 999991, "title": "iso", "actor": "t", "evidence_ids": ["ev-iso-1"]})
    assert r.status_code == 201

    qa = c_a.get("/cases").json()
    qb = c_b.get("/cases").json()
    assert qa["count"] == 1
    assert qb["count"] == 0, "B leaked cases from A — isolation broken"
