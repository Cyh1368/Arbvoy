from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import dataclass
from typing import Any

import aiohttp
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from arbvoy.audit.logger import get_logger
from arbvoy.config import AppConfig


class RobinhoodFeed:
    def __init__(self, config: AppConfig, session: aiohttp.ClientSession | None = None) -> None:
        self._config = config
        self._session = session
        self._bucket_tokens = 10.0
        self._bucket_last = time.monotonic()
        self._lock = asyncio.Lock()
        self._log = get_logger("arbvoy.feeds.robinhood")
        self._private_key = self._load_private_key(config.ROBINHOOD_API_KEY)

    async def get_btc_quote(self) -> tuple[float, float]:
        await self._acquire_token()
        session = await self._ensure_session()
        path = "/api/v1/crypto/trading/best_bid_ask/?symbol=BTC-USD"
        timestamp = str(int(time.time()))
        body = ""
        signature = self._sign_message(timestamp, path, body)
        headers = {
            "x-api-key": self._config.ROBINHOOD_API_KEY,
            "x-timestamp": timestamp,
            "x-signature": signature,
        }
        async with session.get(f"{self._config.ROBINHOOD_BASE_URL}{path}", headers=headers) as resp:
            text = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"robinhood quote request failed: status={resp.status} body={text[:200]}")
            try:
                payload = await resp.json(content_type=None)
            except Exception as exc:
                raise RuntimeError(f"robinhood quote response was not json: {text[:200]}") from exc
        quote = payload.get("results") or payload.get("best_bid_ask") or payload
        bid = float(quote.get("bid_price") or quote.get("bid") or quote.get("best_bid") or 0.0)
        ask = float(quote.get("ask_price") or quote.get("ask") or quote.get("best_ask") or 0.0)
        return bid, ask

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def _acquire_token(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._bucket_last
            self._bucket_tokens = min(10.0, self._bucket_tokens + elapsed * 10.0)
            self._bucket_last = now
            while self._bucket_tokens < 1.0:
                await asyncio.sleep(0.05)
                now = time.monotonic()
                elapsed = now - self._bucket_last
                self._bucket_tokens = min(10.0, self._bucket_tokens + elapsed * 10.0)
                self._bucket_last = now
            self._bucket_tokens -= 1.0

    def _load_private_key(self, encoded: str) -> Ed25519PrivateKey:
        try:
            if "BEGIN" in encoded:
                return serialization.load_pem_private_key(encoded.encode("utf-8"), password=None)  # type: ignore[return-value]
            raw = base64.b64decode(encoded)
            try:
                return serialization.load_pem_private_key(raw, password=None)  # type: ignore[return-value]
            except ValueError:
                return serialization.load_der_private_key(raw, password=None)  # type: ignore[return-value]
        except Exception:
            return Ed25519PrivateKey.generate()

    def _sign_message(self, timestamp: str, path: str, body: str) -> str:
        message = f"{self._config.ROBINHOOD_API_KEY}{timestamp}{path}{body}".encode("utf-8")
        signature = self._private_key.sign(message)
        return base64.b64encode(signature).decode("ascii")

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
