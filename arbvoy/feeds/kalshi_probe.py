from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import aiohttp

from arbvoy.config import AppConfig
from arbvoy.feeds.models import ContractQuote


@dataclass(slots=True)
class KalshiProbeResult:
    contracts: list[ContractQuote]
    http_status: int | None
    response_text: str | None
    source: str


def _auth_headers(config: AppConfig, path: str, body: str = "") -> dict[str, str]:
    timestamp = str(int(time.time() * 1000))
    message = f"{path}{timestamp}{body}".encode("utf-8")
    signature = hmac.new(config.KALSHI_API_SECRET.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return {
        "KALSHI-ACCESS-KEY": config.KALSHI_API_KEY,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "KALSHI-ACCESS-SIGNATURE": signature,
    }


def _parse_contract(market: dict[str, Any]) -> ContractQuote | None:
    ticker = market.get("ticker") or market.get("market_ticker")
    if not ticker:
        return None
    expiry = (
        market.get("close_time")
        or market.get("expected_expiration_time")
        or market.get("expiration_time")
        or market.get("expiry_dt")
        or market.get("close_ts")
        or market.get("end_date")
    )
    expiry_dt = datetime.fromisoformat(str(expiry).replace("Z", "+00:00")) if expiry else datetime.now(timezone.utc)
    strike = (
        market.get("floor_strike")
        or market.get("cap_strike")
        or market.get("functional_strike")
        or market.get("strike_usd")
        or market.get("strike")
    )
    if strike in (None, "", 0, 0.0):
        match = re.search(r"-[TB]([0-9]+(?:\.[0-9]+)?)$", str(ticker))
        strike = float(match.group(1)) if match else 0.0
    return ContractQuote(
        ticker=ticker,
        strike_usd=float(strike),
        expiry_dt=expiry_dt,
        yes_ask=float(market.get("yes_ask", market.get("yes_price", 0.5))),
        no_ask=float(market.get("no_ask", market.get("no_price", 0.5))),
        yes_bid=float(market.get("yes_bid", market.get("yes_price", 0.5))),
        no_bid=float(market.get("no_bid", market.get("no_price", 0.5))),
        volume_24h=float(market.get("volume_24h", 0.0)),
        open_interest=float(market.get("open_interest", 0.0)),
    )


def _liquidity_score(market: dict[str, Any]) -> float:
    for key in ("liquidity_dollars", "volume_dollars", "volume_fp", "volume_24h", "last_price_dollars"):
        value = market.get(key)
        if value not in (None, ""):
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return 0.0


async def fetch_kalshi_contracts(config: AppConfig, session: aiohttp.ClientSession | None = None) -> KalshiProbeResult:
    owns_session = session is None
    client = session or aiohttp.ClientSession()
    try:
        path = "/markets?series_ticker=KXBTC&status=open"
        url = f"https://api.elections.kalshi.com/trade-api/v2{path}"
        async with client.get(url) as resp:
            text = await resp.text()
            try:
                payload = await resp.json(content_type=None)
            except Exception:
                payload = None
            markets = payload.get("markets", []) if isinstance(payload, dict) else []
            markets = sorted(markets, key=_liquidity_score, reverse=True)
            contracts: list[ContractQuote] = []
            for market in markets[:20]:
                ticker = market.get("ticker") or market.get("market_ticker")
                if not ticker:
                    continue
                parsed = _parse_contract(market)
                ob_path = f"/markets/{ticker}/orderbook"
                ob_url = f"https://api.elections.kalshi.com/trade-api/v2{ob_path}"
                async with client.get(ob_url) as ob_resp:
                    ob_payload = await ob_resp.json(content_type=None)
                orderbook = ob_payload.get("orderbook_fp", {}) if isinstance(ob_payload, dict) else {}
                yes_levels = orderbook.get("yes_dollars", []) or []
                no_levels = orderbook.get("no_dollars", []) or []
                best_yes_bid = float(yes_levels[-1][0]) if yes_levels else float(market.get("yes_price", 0.5))
                best_no_bid = float(no_levels[-1][0]) if no_levels else float(market.get("no_price", 0.5))
                yes_ask = 1.0 - best_no_bid if no_levels else 1.0 - best_yes_bid
                no_ask = 1.0 - best_yes_bid if yes_levels else 1.0 - best_no_bid
                contracts.append(
                    ContractQuote(
                        ticker=ticker,
                        strike_usd=parsed.strike_usd if parsed is not None else 0.0,
                        expiry_dt=parsed.expiry_dt if parsed is not None else datetime.now(timezone.utc),
                        yes_ask=yes_ask,
                        no_ask=no_ask,
                        yes_bid=best_yes_bid,
                        no_bid=best_no_bid,
                        volume_24h=float(market.get("volume_24h", market.get("volume_fp", 0.0))),
                        open_interest=float(market.get("open_interest", 0.0)),
                    )
                )
            return KalshiProbeResult(
                contracts=contracts,
                http_status=resp.status,
                response_text=text,
                source="kalshi_api",
            )
    finally:
        if owns_session:
            await client.close()


async def main() -> int:
    from arbvoy.config import load_config

    config = load_config()
    result = await fetch_kalshi_contracts(config)
    print(f"status={result.http_status} source={result.source} contracts={len(result.contracts)}")
    if result.response_text:
        print(result.response_text[:500])
    for contract in result.contracts[:5]:
        print(contract.ticker, contract.strike_usd, contract.yes_ask, contract.no_ask, contract.expiry_dt.isoformat())
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
