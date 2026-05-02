from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

from arbvoy.exceptions import ConfigError


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    KALSHI_API_KEY: str
    KALSHI_API_SECRET: str
    ROBINHOOD_API_KEY: str
    ROBINHOOD_ACCOUNT_NUMBER: str
    ANTHROPIC_API_KEY: str
    KALSHI_BASE_URL: str = "https://trading-api.kalshi.com/trade-api/v2"
    KALSHI_WS_URL: str = "wss://trading-api.kalshi.com/trade-api/ws/v2"
    ROBINHOOD_BASE_URL: str = "https://trading.robinhood.com"
    SNAPSHOT_INTERVAL_SECONDS: float = 1.0
    RING_BUFFER_SIZE: int = 3600
    MIN_EDGE_BPS: int = 300
    MIN_KALSHI_VOLUME_24H: float = 1000.0
    MAX_KALSHI_NOTIONAL_PER_CONTRACT: float = 500.0
    MAX_TOTAL_KALSHI_NOTIONAL: float = 2000.0
    MAX_ROBINHOOD_HEDGE_NOTIONAL: float = 1000.0
    DAILY_LOSS_LIMIT_PCT: float = 0.03
    STOP_LOSS_BPS: int = 150
    PROFIT_TARGET_BPS: int = 300
    TIME_EXIT_HOURS: float = 24.0
    KELLY_FRACTION: float = 0.25
    EVOLUTION_TRADE_INTERVAL: int = 50
    SHADOW_TRADE_COUNT: int = 20
    STRATEGY_POPULATION_SIZE: int = 10
    LOG_FILE_PATH: str = "logs/arbvoy.jsonl"
    DB_PATH: str = "data/arbvoy.db"


def load_config(env_file: str | None = ".env") -> AppConfig:
    if env_file and Path(env_file).exists():
        load_dotenv(env_file)
    try:
        return AppConfig.model_validate(dict(os.environ))
    except Exception as exc:  # pragma: no cover - Pydantic error surface
        raise ConfigError(str(exc)) from exc


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return load_config()
