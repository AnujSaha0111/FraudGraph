from app.main import create_app
from app.storage import db
from app.version import __version__


def test_health_ok_after_init(client):
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["service"] == "fraudgraph"
    assert body["version"] == __version__
    assert body["storage"] == "ok"


def test_health_reports_uninitialized_storage(tmp_path):
    from fastapi.testclient import TestClient

    from app.config import load_settings
    s = load_settings(environ={"FG_BASE_DIR": str(tmp_path),
                               "FG_DB_PATH": str(tmp_path / "nope.duckdb")})
    c = TestClient(create_app(s))
    body = c.get("/health").json()
    assert body["storage"] == "uninitialized"


def test_api_startup_and_placeholders(client):
    res = client.get("/health")
    assert res.status_code == 200

    cases = [
        ("/transactions/1", 3),
        ("/transactions/1/network", 4),
        ("/communities/abc", 4),
    ]
    for path, reserved in cases:
        r = client.get(path)
        assert r.status_code == 501, path
        assert r.json()["owned_by_phase"] == reserved
    # /transactions queue (empty store -> empty queue)
    assert client.get("/transactions").status_code == 200
    # risk/evidence/cases are implemented - with a tmp DB they return
    # 404/422/503 (or 500 if storage missing)
    for path in ("/transactions/1/risk", "/transactions/1/evidence"):
        r = client.get(path)
        assert r.status_code in (404, 422, 503, 500), path
    assert client.get("/cases").status_code == 200   # empty queue is valid


def test_openapi_schema_available(client):
    res = client.get("/openapi.json")
    assert res.status_code == 200
    paths = res.json()["paths"]
    assert "/health" in paths


def test_db_required_tables_present(client):
    conn = db.connect(client.app.state.settings.db_path)
    try:
        assert db.required_tables().issubset(db.existing_tables(conn))
    finally:
        conn.close()
