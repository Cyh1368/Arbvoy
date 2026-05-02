from __future__ import annotations

import uuid
from typing import Any

import aiohttp

from arbvoy.config import AppConfig


class RobinhoodClient:
    def __init__(self, config: AppConfig, session: aiohttp.ClientSession | None = None) -> None:
        self._config = config
        self._session = session

    async def submit_order(self, quantity_btc: float, side: str = "buy", order_type: str = "market") -> dict[str, Any]:
        return {
            "order_id": str(uuid.uuid4()),
            "quantity_btc": quantity_btc,
            "side": side,
            "order_type": order_type,
            "status": "FILLED",
            "filled_price": 0.0,
        }

