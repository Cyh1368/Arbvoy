from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from typing import Any

from arbvoy.config import load_config
from arbvoy.orchestrator import MainOrchestrator, simulate_snapshot
from arbvoy.backtest.engine import BacktestRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ArbitrageVoy")
    parser.add_argument("--dry-run", action="store_true", help="Run without submitting orders")
    parser.add_argument("--paper-trade", action="store_true", help="Use simulated fills")
    parser.add_argument("--live", action="store_true", help="Allow live order submission")
    parser.add_argument(
        "--simulate-snapshot",
        action="store_true",
        help="Emit a simulated signal snapshot and exit",
    )
    parser.add_argument("--backtest", action="store_true", help="Run a historical dry-run backtest")
    parser.add_argument("--backtest-ticker", default=None, help="Historical Kalshi ticker to backtest")
    parser.add_argument(
        "--robinhood-history",
        default=None,
        help="Path to a cached Robinhood quote history CSV",
    )
    parser.add_argument(
        "--spot-history",
        default=None,
        help="Path to a cached BTC spot history CSV",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    config = load_config()
    orchestrator = MainOrchestrator(config=config, dry_run=args.dry_run, paper_trade=not args.live or args.paper_trade)
    if args.backtest:
        runner = BacktestRunner(config)
        result = await runner.run(
            kalshi_ticker=args.backtest_ticker,
            robinhood_history_path=args.robinhood_history,
            spot_history_path=args.spot_history,
        )
        print(f"backtest_points={len(result.points)} backtest_trades={len(result.trades)} report={result.report_path}")
        return 0
    if args.simulate_snapshot:
        await simulate_snapshot(orchestrator)
        return 0
    await orchestrator.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
