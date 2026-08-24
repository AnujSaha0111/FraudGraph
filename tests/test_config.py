import pytest

from app.config import load_settings


def test_defaults():
    s = load_settings(environ={"FG_BASE_DIR": "X:\\nowhere"})
    assert s.env == "dev"
    assert s.api_host == "127.0.0.1"
    assert s.api_port == 8000
    assert s.log_level == "INFO"
    assert s.hub_degree_max == 1000
    assert s.window_back_days == 14
    assert s.window_fwd_days == 2
    assert s.neighbor_cap == 200
    assert s.expansion_depth == 1
    assert s.demo_seed == 42


def test_env_overrides():
    s = load_settings(environ={
        "FG_BASE_DIR": "X:\\nowhere",
        "FG_API_PORT": "9999",
        "FG_LOG_LEVEL": "debug",
        "FG_HUB_DEGREE_MAX": "500",
        "FG_DEMO_SEED": "7",
    })
    assert s.api_port == 9999
    assert s.log_level == "DEBUG"
    assert s.hub_degree_max == 500
    assert s.demo_seed == 7


def test_invalid_log_level_raises():
    with pytest.raises(ValueError):
        load_settings(environ={"FG_BASE_DIR": "X:", "FG_LOG_LEVEL": "loud"})


def test_invalid_port_raises():
    with pytest.raises(ValueError):
        load_settings(environ={"FG_BASE_DIR": "X:", "FG_API_PORT": "70000"})


def test_env_file_loading(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\nFG_DEMO_SEED = 7\nFG_ENV=\"stage\"\n",
        encoding="utf-8")
    s = load_settings(env_file=env_file,
                      environ={"FG_BASE_DIR": str(tmp_path)})
    assert s.demo_seed == 7
    assert s.env == "stage"


def test_db_path_default_under_data_dir():
    s = load_settings(environ={"FG_BASE_DIR": "X:\\proj"})
    assert s.db_path.as_posix().endswith("data/app/fraudgraph.duckdb")
