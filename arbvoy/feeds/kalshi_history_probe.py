from __future__ import annotations

import asyncio

from arbvoy.backtest.kalshi_history import fetch_historical_market_summaries
from arbvoy.backtest.kalshi_history import fetch_historical_kalshi_series


async def main() -> int:
    from arbvoy.config import load_config

    config = load_config()
    summaries = await fetch_historical_market_summaries(config)
    if not summaries:
        raise RuntimeError("no historical Kalshi markets available")
    selected = max(summaries, key=lambda item: (item.volume, item.liquidity, -abs(item.strike)))
    series = await fetch_historical_kalshi_series(config, ticker=selected.ticker)
    print(f"ticker={series.contract.ticker} points={len(series.points)}")
    if series.points:
        print(series.points[0][0].isoformat(), series.points[-1][0].isoformat())
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
