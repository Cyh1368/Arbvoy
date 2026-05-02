from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp

from arbvoy.config import AppConfig


@dataclass(slots=True)
class SpotHistoryPoint:
    timestamp: datetime
    mid: float
    bid: float
    ask: float
    source: str


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 10**12:
            seconds /= 1000.0
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


async def fetch_btc_spot_history(
    config: AppConfig,
    start_time: datetime,
    end_time: datetime,
    session: aiohttp.ClientSession | None = None,
) -> list[SpotHistoryPoint]:
    owns_session = session is None
    client = session or aiohttp.ClientSession()
    try:
        start_ts = int(_parse_ts(start_time).timestamp())
        end_ts = int(_parse_ts(end_time).timestamp())
        if end_ts <= start_ts:
            end_ts = start_ts + 3600
        url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart/range"
        params = {"vs_currency": "usd", "from": start_ts, "to": end_ts}
        async with client.get(url, params=params, headers={"accept": "application/json"}) as resp:
            payload = await resp.json(content_type=None)
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"coingecko request failed: status={resp.status} body={text[:200]}")
        prices = payload.get("prices", []) if isinstance(payload, dict) else []
        if not prices:
            raise RuntimeError("coingecko returned no BTC prices")
        points: list[SpotHistoryPoint] = []
        for ts_ms, mid in prices:
            mid_f = float(mid)
            spread_pct = 0.0015
            half_spread = mid_f * spread_pct / 2.0
            points.append(
                SpotHistoryPoint(
                    timestamp=datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=timezone.utc),
                    mid=mid_f,
                    bid=max(mid_f - half_spread, 0.0),
                    ask=mid_f + half_spread,
                    source="coingecko",
                )
            )
        return points
    finally:
        if owns_session:
            await client.close()


async def fetch_current_btc_spot(session: aiohttp.ClientSession | None = None) -> float:
    owns_session = session is None
    client = session or aiohttp.ClientSession()
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {"ids": "bitcoin", "vs_currencies": "usd"}
        async with client.get(url, params=params, headers={"accept": "application/json"}) as resp:
            payload = await resp.json(content_type=None)
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"coingecko spot request failed: status={resp.status} body={text[:200]}")
        return float((payload.get("bitcoin") or {}).get("usd"))
    finally:
        if owns_session:
            await client.close()


def save_spot_history(points: list[SpotHistoryPoint], output_path: str) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as handle:
        import csv

        writer = csv.DictWriter(handle, fieldnames=["timestamp", "mid", "bid", "ask", "source"])
        writer.writeheader()
        for point in points:
            writer.writerow(
                {
                    "timestamp": point.timestamp.isoformat(),
                    "mid": point.mid,
                    "bid": point.bid,
                    "ask": point.ask,
                    "source": point.source,
                }
            )
    return out
