import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_settings
from app.main import create_app

# real-data gating
# Tests marked `real_data` exercise IEEE-CIS-derived artifacts that are NOT distributed with this repository (see README "Data availability" and scripts/setup_data.py). They run only when BOTH hold:
# 1. FG_REAL_DATA=1 is set explicitly, and
# 2. the locally prepared artifacts exist.
# Otherwise they are skipped with an explicit reason — nothing is hidden and no assertion is weakened: the same tests execute unchanged under full mode.

REAL_DATA_FILES = (
    "data/processed/ieee_train_transaction.parquet",
    "data/processed/experiment_base.parquet",
    "data/processed/production_features.parquet",
    "data/processed/graph_links.parquet",
)

SKIP_REASON_NO_FLAG = (
    "IEEE-CIS real-data artifacts not available; set FG_REAL_DATA=1 after "
    "obtaining and preparing the dataset (see scripts/setup_data.py)"
)


def _missing_real_data_files() -> list[str]:
    root = Path(__file__).resolve().parents[1]
    return [p for p in REAL_DATA_FILES if not (root / p).exists()]


def _real_data_mode() -> tuple[bool, str]:
    """Return (run_real_data_tests, skip_reason)."""
    if os.environ.get("FG_REAL_DATA") != "1":
        return False, SKIP_REASON_NO_FLAG
    missing = _missing_real_data_files()
    if missing:
        return False, (
            "FG_REAL_DATA=1 is set but locally prepared artifacts are missing: "
            f"{', '.join(missing)} (see scripts/setup_data.py)")
    return True, ""


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_data: requires locally prepared IEEE-CIS artifacts; gated by "
        "FG_REAL_DATA=1 (see scripts/setup_data.py)",
    )


def pytest_sessionstart(session):
    run_real, reason = _real_data_mode()
    if run_real:
        mode = "FULL REAL-DATA VALIDATION (FG_REAL_DATA=1, artifacts present)"
    elif os.environ.get("FG_REAL_DATA") == "1":
        mode = f"PUBLIC / DATA-FREE (requested full mode unavailable: {reason})"
    else:
        mode = ("PUBLIC / DATA-FREE validation "
                "(IEEE-CIS real-data tests are gated; see scripts/setup_data.py)")
    reporter = session.config.pluginmanager.getplugin("terminalreporter")
    if reporter is not None:
        reporter.write_sep("=", f"FraudGraph test mode: {mode}")


def pytest_collection_modifyitems(config, items):
    run_real, reason = _real_data_mode()
    if run_real:
        return
    skip = pytest.mark.skip(reason=reason)
    for item in items:
        if "real_data" in item.keywords:
            item.add_marker(skip)


@pytest.fixture()
def settings(tmp_path):
    return load_settings(environ={
        "FG_BASE_DIR": str(tmp_path),
        "FG_DB_PATH": str(tmp_path / "test.duckdb"),
    })


@pytest.fixture()
def initialized_settings(settings):
    from app.storage import db
    db.init_db(settings.db_path)
    return settings


@pytest.fixture()
def client(initialized_settings):
    return TestClient(create_app(initialized_settings))
