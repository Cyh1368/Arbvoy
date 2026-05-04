from __future__ import annotations

import asyncio
from datetime import date as date_cls
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from arbvoy.config import AppConfig
from arbvoy.feeds.models import ContractQuote


@dataclass(slots=True)
class KalshiHistorySeries:
    contract: ContractQuote
    points: list[tuple[datetime, float, float, float, float, float]]


@dataclass(slots=True)
class HistoricalMarketSummary:
    ticker: str
    volume: float
    liquidity: float
    strike: float
    last_price: float
    previous_price: float
    yes_bid: float
    yes_ask: float
    close_time: datetime
    open_time: datetime



def _parse_ts(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


async def fetch_historical_kalshi_series(
    config: AppConfig,
    ticker: str,
    series_ticker: str = "KXBTC",
    period_interval: int = 1,
    session: aiohttp.ClientSession | None = None,
) -> KalshiHistorySeries:
    owns_session = session is None
    client = session or aiohttp.ClientSession()
    try:
        markets_url = "https://api.elections.kalshi.com/trade-api/v2/historical/markets"
        market = None
        cursor: str | None = None
        while True:
            markets_params = {"series_ticker": series_ticker, "limit": 1000}
            if cursor:
                markets_params["cursor"] = cursor
            async with client.get(markets_url, params=markets_params) as resp:
                market_payload = await resp.json(content_type=None)
            markets = market_payload.get("markets", []) if isinstance(market_payload, dict) else []
            market = next((item for item in markets if item.get("ticker") == ticker), None)
            if market is not None:
                break
            cursor = market_payload.get("cursor") if isinstance(market_payload, dict) else None
            if not cursor:
                break
        if market is None:
            raise RuntimeError(f"historical Kalshi market not found: {ticker}")
        open_time = _parse_ts(market.get("open_time") or market.get("created_time") or market.get("close_time") or datetime.now(timezone.utc))
        close_time = _parse_ts(market.get("close_time") or market.get("expected_expiration_time") or market.get("expiration_time") or datetime.now(timezone.utc))
        if close_time <= open_time:
            close_time = datetime.now(timezone.utc)
        url = f"https://api.elections.kalshi.com/trade-api/v2/historical/markets/{ticker}/candlesticks"
        params = {
            "start_ts": int(open_time.timestamp()),
            "end_ts": int(close_time.timestamp()),
            "period_interval": period_interval,
        }
        async with client.get(url, params=params) as resp:
            payload = await resp.json(content_type=None)
            print(f"DEBUG: candlesticks URL: {url} params: {params} payload_keys: {list(payload.keys()) if isinstance(payload, dict) else 'Not a dict'}")
        contract = ContractQuote(
            ticker=ticker,
            strike_usd=float(market.get("floor_strike") or market.get("cap_strike") or market.get("functional_strike") or 0.0),
            expiry_dt=_parse_ts(market.get("expected_expiration_time") or market.get("expiration_time") or market.get("close_time") or datetime.now(timezone.utc)),
            yes_ask=float(market.get("yes_ask_dollars") or market.get("yes_ask") or market.get("yes_bid_dollars") or 0.5),
            no_ask=float(market.get("no_ask_dollars") or market.get("no_ask") or market.get("no_bid_dollars") or 0.5),
            yes_bid=float(market.get("yes_bid_dollars") or market.get("yes_bid") or 0.5),
            no_bid=float(market.get("no_bid_dollars") or market.get("no_bid") or 0.5),
            volume_24h=float(market.get("volume_24h_fp") or market.get("volume_fp") or 0.0),
            open_interest=float(market.get("open_interest_fp") or market.get("open_interest") or 0.0),
        )
        candlesticks = payload.get("candlesticks", []) if isinstance(payload, dict) else []
        if not candlesticks and isinstance(payload, dict):
            candlesticks = payload.get("candles", []) or payload.get("data", [])
        points: list[tuple[datetime, float, float, float, float, float]] = []
        for candle in candlesticks:
            end_ts = candle.get("end_period_ts")
            if end_ts is None:
                continue
            # DEBUG
            # print(f"DEBUG: candle={candle}")
            
            yes_bid = candle.get("yes_bid", {})
            yes_ask = candle.get("yes_ask", {})
            
            # Helper to get best price
            def get_price(p_dict):
                return float(p_dict.get("close_dollars") or p_dict.get("close") or p_dict.get("open_dollars") or p_dict.get("open") or 0.0)

            points.append(
                (
                    _parse_ts(candle.get("end_period_ts")),
                    get_price(yes_bid),
                    get_price(yes_ask),
                    get_price(candle.get("price", {})),
                    float(candle.get("volume") or candle.get("volume_fp") or 0.0),
                    float(candle.get("open_interest") or candle.get("open_interest_fp") or 0.0),
                )
            )
        return KalshiHistorySeries(contract=contract, points=points)
    finally:
        if owns_session:
            await client.close()


async def fetch_historical_market_summaries(
    config: AppConfig,
    series_ticker: str = "KXBTC",
    session: aiohttp.ClientSession | None = None,
) -> list[HistoricalMarketSummary]:
    owns_session = session is None
    client = session or aiohttp.ClientSession()
    try:
        url = "https://api.elections.kalshi.com/trade-api/v2/historical/markets"
        summaries: list[HistoricalMarketSummary] = []
        cursor: str | None = None
        while True:
            params = {"series_ticker": series_ticker, "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            async with client.get(url, params=params) as resp:
                payload = await resp.json(content_type=None)
            markets = payload.get("markets", []) if isinstance(payload, dict) else []
            for market in markets:
                ticker = market.get("ticker")
                if not ticker:
                    continue
                summaries.append(
                    HistoricalMarketSummary(
                        ticker=ticker,
                        volume=float(market.get("volume_24h_fp") or market.get("volume_fp") or 0.0),
                        liquidity=float(market.get("liquidity_dollars") or 0.0),
                        strike=float(market.get("floor_strike") or market.get("cap_strike") or market.get("functional_strike") or 0.0),
                        last_price=float(market.get("last_price_dollars") or 0.0),
                        previous_price=float(market.get("previous_price_dollars") or 0.0),
                        yes_bid=float(market.get("yes_bid_dollars") or market.get("yes_bid") or 0.0),
                        yes_ask=float(market.get("yes_ask_dollars") or market.get("yes_ask") or 0.0),
                        close_time=_parse_ts(market.get("close_time") or market.get("settlement_ts") or market.get("latest_expiration_time") or datetime.now(timezone.utc)),
                        open_time=_parse_ts(market.get("open_time") or market.get("created_time") or market.get("close_time") or datetime.now(timezone.utc)),
                    )
                )
            cursor = payload.get("cursor") if isinstance(payload, dict) else None
            if not cursor:
                break
        return summaries
    finally:
        if owns_session:
            await client.close()


async def fetch_historical_tickers_for_date(
    config: AppConfig,
    target_date: date_cls,
    series_ticker: str = "KXBTC",
    session: aiohttp.ClientSession | None = None,
) -> list[HistoricalMarketSummary]:
    summaries = await fetch_historical_market_summaries(config, series_ticker=series_ticker, session=session)
    start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return [
        market
        for market in summaries
        if market.open_time < end and market.close_time >= start
    ]


async def main() -> int:
    from arbvoy.config import load_config

    config = load_config()
    series = await fetch_historical_kalshi_series(config, ticker="KXBTC-26MAY0317-T68250")
    print(f"ticker={series.contract.ticker} points={len(series.points)}")
    if series.points:
        first = series.points[0]
        last = series.points[-1]
        print(f"first={first[0].isoformat()} last={last[0].isoformat()} price={last[3]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
