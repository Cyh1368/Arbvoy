from __future__ import annotations

import asyncio
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from arbvoy.config import AppConfig
from arbvoy.feeds.robinhood_feed import RobinhoodFeed
from arbvoy.backtest.spot_history import fetch_btc_spot_history


@dataclass(slots=True)
class RobinhoodQuotePoint:
    timestamp: datetime
    bid: float
    ask: float
    source: str = "robinhood"


def load_robinhood_history(path: str) -> list[RobinhoodQuotePoint]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    points: list[RobinhoodQuotePoint] = []
    with file_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            bid = row.get("bid")
            ask = row.get("ask")
            mid = row.get("mid")
            if (bid in (None, "")) or (ask in (None, "")):
                if mid not in (None, ""):
                    mid_value = float(mid)
                    half_spread = mid_value * 0.0015 / 2.0
                    bid = str(max(mid_value - half_spread, 0.0))
                    ask = str(mid_value + half_spread)
                else:
                    continue
            points.append(
                RobinhoodQuotePoint(
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    bid=float(bid),
                    ask=float(ask),
                    source=row.get("source", "robinhood"),
                )
            )
    return points


async def record_robinhood_history(config: AppConfig, samples: int = 30, interval_seconds: float = 1.0, output_path: str = "artifacts/robinhood_history.csv") -> list[RobinhoodQuotePoint]:
    feed = RobinhoodFeed(config)
    points: list[RobinhoodQuotePoint] = []
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    try:
        for _ in range(samples):
            bid, ask = await feed.get_btc_quote()
            points.append(RobinhoodQuotePoint(timestamp=datetime.now(timezone.utc), bid=bid, ask=ask))
            await asyncio.sleep(interval_seconds)
    finally:
        await feed.close()
    with Path(output_path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "bid", "ask", "source"])
        writer.writeheader()
        for point in points:
            writer.writerow(
                {
                    "timestamp": point.timestamp.isoformat(),
                    "bid": point.bid,
                    "ask": point.ask,
                    "source": point.source,
                }
            )
    return points


async def fetch_historical_robinhood_history(
    config: AppConfig,
    start_time: datetime,
    end_time: datetime,
    output_path: str = "artifacts/robinhood_history.csv",
) -> list[RobinhoodQuotePoint]:
    spot_points = await fetch_btc_spot_history(config, start_time=start_time, end_time=end_time)
    robinhood_points = [RobinhoodQuotePoint(timestamp=point.timestamp, bid=point.bid, ask=point.ask, source=point.source) for point in spot_points]
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with Path(output_path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "bid", "ask", "source"])
        writer.writeheader()
        for point in robinhood_points:
            writer.writerow(
                {
                    "timestamp": point.timestamp.isoformat(),
                    "bid": point.bid,
                    "ask": point.ask,
                    "source": point.source,
                }
            )
    return robinhood_points


async def main() -> int:
    from arbvoy.config import load_config

    config = load_config()
    now = datetime.now(timezone.utc)
    points = await fetch_historical_robinhood_history(config, start_time=now, end_time=now)
    print(f"samples={len(points)} source={points[0].source if points else 'none'}")
    if points:
        print(f"first={points[0].timestamp.isoformat()} last={points[-1].timestamp.isoformat()} bid={points[-1].bid} ask={points[-1].ask}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
