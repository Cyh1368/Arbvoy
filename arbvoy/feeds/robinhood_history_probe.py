from __future__ import annotations

import asyncio

from arbvoy.backtest.robinhood_history import fetch_historical_robinhood_history, load_robinhood_history


async def main() -> int:
    from arbvoy.config import load_config

    config = load_config()
    from datetime import datetime, timedelta, timezone

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=1)
    points = await fetch_historical_robinhood_history(config, start_time=start_time, end_time=end_time)
    print(f"historical_points={len(points)} source={points[0].source if points else 'none'}")
    cached = load_robinhood_history("artifacts/robinhood_history.csv")
    print(f"cached={len(cached)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
