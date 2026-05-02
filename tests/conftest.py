from __future__ import annotations

import pytest

from arbvoy.config import AppConfig


def make_config(tmp_path: object | None = None) -> AppConfig:
    db_path = "test.db"
    log_path = "test.jsonl"
    if tmp_path is not None:
        db_path = str(tmp_path / "arbvoy.db")
        log_path = str(tmp_path / "arbvoy.jsonl")
    return AppConfig(
        KALSHI_API_KEY="k",
        KALSHI_API_SECRET="s",
        ROBINHOOD_API_KEY="-----BEGIN PRIVATE KEY-----\nMC4CAQAwBQYDK2VwBCIEIOKZsZg1rYFzv0cQZyG0qj3K6w3T0h6yL7m4xkqD7JQ4\n-----END PRIVATE KEY-----",
        ROBINHOOD_ACCOUNT_NUMBER="acct",
        ANTHROPIC_API_KEY="anthropic",
        LOG_FILE_PATH=log_path,
        DB_PATH=db_path,
    )


@pytest.fixture()
def app_config(tmp_path: object) -> AppConfig:
    return make_config(tmp_path)

