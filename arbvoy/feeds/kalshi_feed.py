from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import aiohttp

from arbvoy.audit.logger import get_logger, log_event
from arbvoy.config import AppConfig
from arbvoy.exceptions import FeedError
from arbvoy.feeds.models import ContractQuote
from arbvoy.feeds.kalshi_probe import fetch_kalshi_contracts


class KalshiFeed:
    def __init__(self, config: AppConfig, session: aiohttp.ClientSession | None = None) -> None:
        self._config = config
        self._session = session
        self._contracts: dict[str, ContractQuote] = {}
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._log = get_logger("arbvoy.feeds.kx")

    async def start(self) -> None:
        await self._seed_contracts()
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(BaseException):
                await self._task
        if self._session is not None:
            await self._session.close()

    async def get_contracts(self) -> list[ContractQuote]:
        return list(self._contracts.values())

    def _auth_headers(self, path: str, body: str = "") -> dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        message = f"{path}{timestamp}{body}".encode("utf-8")
        signature = hmac.new(self._config.KALSHI_API_SECRET.encode("utf-8"), message, hashlib.sha256).hexdigest()
        return {
            "KALSHI-ACCESS-KEY": self._config.KALSHI_API_KEY,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": signature,
        }

    async def _seed_contracts(self) -> None:
        try:
            result = await fetch_kalshi_contracts(self._config, session=await self._ensure_session())
            for contract in result.contracts:
                self._contracts[contract.ticker] = contract
        except Exception as exc:
            self._log.warning("seed_contracts_failed", extra={"event_type": "ERROR", "error": str(exc)})

    async def _run_loop(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                session = await self._ensure_session()
                async with session.ws_connect(self._config.KALSHI_WS_URL, heartbeat=30) as ws:
                    await ws.send_json({"type": "subscribe", "channels": ["orderbook_delta"], "series": ["KXBTC"]})
                    backoff = 1.0
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            self._handle_ws_message(msg.json())
                        elif msg.type in {aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                            raise FeedError("websocket disconnected")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._log.warning("feed_reconnect", extra={"event_type": "ERROR", "error": str(exc)})
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 60.0)

    def _handle_ws_message(self, payload: dict[str, Any]) -> None:
        data = payload.get("data") or payload
        if isinstance(data, list):
            for item in data:
                self._update_contract(item)
        elif isinstance(data, dict):
            self._update_contract(data)

    def _update_contract(self, item: dict[str, Any]) -> None:
        ticker = item.get("ticker") or item.get("market_ticker")
        if not ticker:
            return
        contract = self._contracts.get(ticker)
        if contract is None:
            contract = ContractQuote(
                ticker=ticker,
                strike_usd=float(item.get("strike_usd", 0.0)),
                expiry_dt=datetime.fromisoformat(item.get("expiry_dt")) if item.get("expiry_dt") else datetime.now(timezone.utc),
                yes_ask=float(item.get("yes_ask", 0.5)),
                no_ask=float(item.get("no_ask", 0.5)),
                yes_bid=float(item.get("yes_bid", 0.5)),
                no_bid=float(item.get("no_bid", 0.5)),
                volume_24h=float(item.get("volume_24h", 0.0)),
                open_interest=float(item.get("open_interest", 0.0)),
            )
        else:
            contract = ContractQuote(
                ticker=contract.ticker,
                strike_usd=float(item.get("strike_usd", contract.strike_usd)),
                expiry_dt=contract.expiry_dt,
                yes_ask=float(item.get("yes_ask", contract.yes_ask)),
                no_ask=float(item.get("no_ask", contract.no_ask)),
                yes_bid=float(item.get("yes_bid", contract.yes_bid)),
                no_bid=float(item.get("no_bid", contract.no_bid)),
                volume_24h=float(item.get("volume_24h", contract.volume_24h)),
                open_interest=float(item.get("open_interest", contract.open_interest)),
            )
        self._contracts[ticker] = contract

    def _parse_contract(self, market: dict[str, Any]) -> ContractQuote | None:
        ticker = market.get("ticker") or market.get("market_ticker")
        if not ticker:
            return None
        expiry = market.get("expiry_dt") or market.get("close_ts") or market.get("end_date")
        expiry_dt = datetime.fromisoformat(expiry) if expiry else datetime.now(timezone.utc)
        return ContractQuote(
            ticker=ticker,
            strike_usd=float(market.get("strike_usd", market.get("strike", 0.0))),
            expiry_dt=expiry_dt,
            yes_ask=float(market.get("yes_ask", market.get("yes_price", 0.5))),
            no_ask=float(market.get("no_ask", market.get("no_price", 0.5))),
            yes_bid=float(market.get("yes_bid", market.get("yes_price", 0.5))),
            no_bid=float(market.get("no_bid", market.get("no_price", 0.5))),
            volume_24h=float(market.get("volume_24h", 0.0)),
            open_interest=float(market.get("open_interest", 0.0)),
        )

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
