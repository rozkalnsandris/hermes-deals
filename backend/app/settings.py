from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_env: str
    log_level: str
    database_url: str
    raw_snapshot_dir: Path
    sources_config: Path
    http_user_agent: str


def get_settings() -> Settings:
    return Settings(
        app_env=os.getenv("APP_ENV", "development"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        database_url=os.environ["DATABASE_URL"],
        raw_snapshot_dir=Path(os.getenv("RAW_SNAPSHOT_DIR", "/data/raw")),
        sources_config=Path(os.getenv("SOURCES_CONFIG", "/app/config/sources.json")),
        http_user_agent=os.getenv("HTTP_USER_AGENT", "HermesDeals/0.1"),
    )
