from __future__ import annotations

import argparse
import asyncio
from datetime import date

from arbvoy.backtest.kalshi_history import fetch_historical_tickers_for_date


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List Kalshi tickers active on a given date")
    parser.add_argument("date", help="UTC date in YYYY-MM-DD format")
    parser.add_argument(
        "--series-ticker",
        default="KXBTC",
        help="Kalshi series ticker to scan, default: KXBTC",
    )
    return parser.parse_args()


async def main() -> int:
    from arbvoy.config import load_config

    args = parse_args()
    target_date = date.fromisoformat(args.date)
    config = load_config()
    markets = await fetch_historical_tickers_for_date(config, target_date=target_date, series_ticker=args.series_ticker)
    print(f"date={target_date.isoformat()} series={args.series_ticker} count={len(markets)}")
    for market in markets:
        print(
            market.ticker,
            f"strike={market.strike:.2f}",
            f"open={market.open_time.isoformat()}",
            f"close={market.close_time.isoformat()}",
            f"last={market.last_price:.4f}",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
