from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass
from typing import Any

import aiohttp

from arbvoy.config import AppConfig


class KalshiClient:
    def __init__(self, config: AppConfig, session: aiohttp.ClientSession | None = None) -> None:
        self._config = config
        self._session = session

    async def submit_order(self, ticker: str, side: str, price: float, notional: float, order_type: str = "limit") -> dict[str, Any]:
        return {
            "order_id": str(uuid.uuid4()),
            "ticker": ticker,
            "side": side,
            "price": price,
            "notional": notional,
            "status": "FILLED",
            "filled_notional": notional,
        }

    async def poll_order(self, order_id: str) -> dict[str, Any]:
        return {"order_id": order_id, "status": "FILLED", "filled_notional": 0.0}

    async def cancel_order(self, order_id: str) -> None:
        return None

    async def close_position(self, ticker: str, notional: float) -> None:
        return None

