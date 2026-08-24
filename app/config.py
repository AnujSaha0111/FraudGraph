# Centralized configuration.
# Precedence: environment variables (FG_*) > .env file at base_dir > defaults. Paths default to repository-relative locations; every consumer must take paths from Settings — no hardcoded paths elsewhere.

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ENV_PREFIX = "FG_"
LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        key = key.removeprefix(ENV_PREFIX)
        values[key] = val.strip().strip('"').strip("'")
    return values


def _base_dir(environ: dict[str, str]) -> Path:
    if "FG_BASE_DIR" in environ:
        return Path(environ["FG_BASE_DIR"]).resolve()
    return Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    env: str
    api_host: str
    api_port: int
    log_level: str
    base_dir: Path
    db_path: Path
    processed_dir: Path
    reports_dir: Path
    model_dir: Path
    frontend_dist_dir: Path
    hub_degree_max: int
    window_back_days: int
    window_fwd_days: int
    neighbor_cap: int
    expansion_depth: int
    demo_seed: int
    min_label_lag_days: int


def load_settings(env_file: Path | None = None,
                  environ: dict[str, str] | None = None) -> Settings:
    env_source = dict(os.environ if environ is None else environ)
    file_values = _load_env_file(
        env_file if env_file is not None else
        _base_dir(env_source) / ".env")

    def get(key: str, default: str | None = None) -> str:
        return env_source.get(ENV_PREFIX + key,
                              file_values.get(key, default))

    def get_int(key: str, default: int) -> int:
        return int(get(key, str(default)))

    base = _base_dir(env_source)
    data_dir = Path(get("DATA_DIR", str(base / "data")))
    log_level = get("LOG_LEVEL", "INFO").upper()
    if log_level not in LOG_LEVELS:
        raise ValueError(f"invalid LOG_LEVEL: {log_level!r}")
    port = get_int("API_PORT", 8000)
    if not (0 < port < 65536):
        raise ValueError(f"invalid API_PORT: {port}")

    return Settings(
        env=get("ENV", "dev"),
        api_host=get("API_HOST", "127.0.0.1"),
        api_port=port,
        log_level=log_level,
        base_dir=base,
        db_path=Path(get("DB_PATH", str(data_dir / "app" /
                                        "fraudgraph.duckdb"))),
        processed_dir=data_dir / "processed",
        reports_dir=Path(get("REPORTS_DIR", str(base / "reports"))),
        model_dir=Path(get("MODEL_DIR", str(base / "models"))),
        frontend_dist_dir=base / "frontend" / "dist",
        hub_degree_max=get_int("HUB_DEGREE_MAX", 1000),
        window_back_days=get_int("WINDOW_BACK_DAYS", 14),
        window_fwd_days=get_int("WINDOW_FWD_DAYS", 2),
        neighbor_cap=get_int("NEIGHBOR_CAP", 200),
        expansion_depth=get_int("EXPANSION_DEPTH", 1),
        demo_seed=get_int("DEMO_SEED", 42),
        min_label_lag_days=get_int("MIN_LABEL_LAG_DAYS", 7),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
