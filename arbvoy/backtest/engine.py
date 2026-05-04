from __future__ import annotations

import asyncio
import csv
import json
import uuid
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from arbvoy.audit.logger import get_logger
from arbvoy.backtest.kalshi_history import fetch_historical_kalshi_series
from arbvoy.backtest.kalshi_history import fetch_historical_market_summaries
from arbvoy.backtest.models import BacktestTrade, HistoricalPoint
from arbvoy.backtest.report import BacktestReport
from arbvoy.backtest.robinhood_history import RobinhoodQuotePoint, fetch_historical_robinhood_history, load_robinhood_history, record_robinhood_history
from arbvoy.config import AppConfig
from arbvoy.feeds.models import ContractQuote, MarketSnapshot
from arbvoy.journal.db import JournalDB
from arbvoy.risk.governor import RiskGovernor
from arbvoy.signals.probability_model import ProbabilityModel
from arbvoy.signals.signal_engine import SignalEngine
from arbvoy.signals.vol_estimator import VolEstimator
from arbvoy.strategy.models import EntryConditions, ExitTriggers, RegimeTag, SizingRules, Strategy, StrategyStatus
from arbvoy.strategy.registry import StrategyRegistry
from arbvoy.strategy.selector import StrategySelector


@dataclass(slots=True)
class BacktestResult:
    points: list[HistoricalPoint]
    trades: list[BacktestTrade]
    report_path: Path | None


class BacktestRunner:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._log = get_logger("arbvoy.backtest")

    async def run(
        self,
        kalshi_ticker: str | None = None,
        robinhood_history_path: str | None = None,
        spot_history_path: str | None = None,
        output_dir: str = "artifacts",
    ) -> BacktestResult:
        summaries = await fetch_historical_market_summaries(self._config)
        if not summaries:
            raise RuntimeError("no historical Kalshi markets available")
        if kalshi_ticker is None:
            selected = self._select_backtest_market(summaries)
            kalshi_ticker = selected.ticker
        kalshi = await fetch_historical_kalshi_series(self._config, ticker=kalshi_ticker)
        robinhood_points = load_robinhood_history(spot_history_path or robinhood_history_path) if (spot_history_path or robinhood_history_path) else []
        if not robinhood_points:
            robinhood_path = str(Path(output_dir) / "robinhood_history.csv")
            try:
                robinhood_points = await fetch_historical_robinhood_history(
                    self._config,
                    start_time=kalshi.contract.expiry_dt - timedelta(days=14),
                    end_time=kalshi.contract.expiry_dt,
                    output_path=robinhood_path,
                )
            except Exception:
                await record_robinhood_history(self._config, samples=20, interval_seconds=1.0, output_path=robinhood_path)
                robinhood_points = load_robinhood_history(robinhood_path)
        points = self._build_points(kalshi, robinhood_points)
        trades = self._simulate_trades(points)
        report = BacktestReport(points=points, trades=trades)
        report_path = report.write(output_dir=output_dir)
        return BacktestResult(points=points, trades=trades, report_path=report_path)

    def _select_backtest_market(self, summaries: list[Any]) -> Any:
        def last_price(item: Any) -> float:
            return float(getattr(item, "last_price", 0.0) or 0.0)

        liquid_candidates = [item for item in summaries if 0.2 <= last_price(item) <= 0.8]
        candidates = liquid_candidates or summaries
        ranked = sorted(
            candidates,
            key=lambda item: (
                abs(last_price(item) - 0.5),
                -float(item.volume),
                -float(item.liquidity),
            ),
        )
        return ranked[0]

    def _build_points(
        self,
        kalshi: Any,
        robinhood_points: list[RobinhoodQuotePoint],
    ) -> list[HistoricalPoint]:
        if not kalshi.points or not robinhood_points:
            return []
        
        points: list[HistoricalPoint] = []
        vol = VolEstimator(self._config.RING_BUFFER_SIZE)
        model = ProbabilityModel()
        
        # Sort both by timestamp
        kalshi_points = sorted(kalshi.points, key=lambda item: item[0])
        rh_points = sorted(robinhood_points, key=lambda item: item.timestamp)
        rh_times = [p.timestamp.timestamp() for p in rh_points]
        rh_bids = [p.bid for p in rh_points]
        rh_asks = [p.ask for p in rh_points]

        import numpy as np

        for kp in kalshi_points:
            ts, yes_bid, yes_ask, price, volume, oi = kp
            ts_val = ts.timestamp()
            
            # Interpolate spot prices
            if ts_val <= rh_times[0]:
                bid, ask = rh_bids[0], rh_asks[0]
            elif ts_val >= rh_times[-1]:
                bid, ask = rh_bids[-1], rh_asks[-1]
            else:
                bid = float(np.interp(ts_val, rh_times, rh_bids))
                ask = float(np.interp(ts_val, rh_times, rh_asks))
            
            spot_mid = (bid + ask) / 2.0
            vol.update(spot_mid)
            
            dte_hours = max((kalshi.contract.expiry_dt - ts).total_seconds() / 3600.0, 0.0)
            implied_prob = max(min(float(yes_ask), 1.0), 0.0)
            
            model_prob = None
            edge_bps = None
            vol_value = None
            
            if vol.has_sufficient_data():
                vol_value = vol.annualized_vol()
                model_prob = model.model_probability(
                    spot_mid,
                    kalshi.contract.strike_usd,
                    dte_hours / 24.0,
                    vol_value,
                    r=0.0,
                    cap_strike=kalshi.contract.cap_strike_usd
                )
                edge_bps = (model_prob - implied_prob) * 10000.0
            
            contract = ContractQuote(
                ticker=kalshi.contract.ticker,
                strike_usd=kalshi.contract.strike_usd,
                cap_strike_usd=kalshi.contract.cap_strike_usd,
                expiry_dt=kalshi.contract.expiry_dt,
                yes_ask=max(min(yes_ask, 1.0), 0.0),
                no_ask=max(min(1.0 - yes_bid, 1.0), 0.0),
                yes_bid=max(min(yes_bid, 1.0), 0.0),
                no_bid=max(min(1.0 - yes_ask, 1.0), 0.0),
                volume_24h=volume,
                open_interest=oi,
            )
            points.append(
                HistoricalPoint(
                    timestamp=ts,
                    btc_spot_mid=spot_mid,
                    btc_spot_bid=bid,
                    btc_spot_ask=ask,
                    contract=contract,
                    model_prob=model_prob,
                    implied_prob=implied_prob,
                    edge_bps=edge_bps,
                    hours_to_expiry=dte_hours,
                    vol=vol_value,
                )
            )
        return points

    def _simulate_trades(self, points: list[HistoricalPoint]) -> list[BacktestTrade]:
        if not points:
            return []
        strategy = Strategy(
            strategy_id="backtest-seed",
            parent_id=None,
            generation=0,
            status=StrategyStatus.LIVE,
            regime_tags=[RegimeTag.ANY],
            entry_conditions=EntryConditions(),
            sizing_rules=SizingRules(),
            exit_triggers=ExitTriggers(),
            mutation_rationale="backtest seed",
        )
        signal_config = self._config.model_copy(update={"MIN_KALSHI_VOLUME_24H": 0.0})
        signal_engine = SignalEngine(signal_config)
        vol = VolEstimator(self._config.RING_BUFFER_SIZE)
        model = ProbabilityModel()
        selector = StrategySelector()
        trades: list[BacktestTrade] = []
        open_trade: dict[str, Any] | None = None
        for point in points:
            vol.update(point.btc_spot_mid)
            snapshot = MarketSnapshot(
                timestamp=point.timestamp,
                btc_spot_mid=point.btc_spot_mid,
                btc_spot_bid=point.btc_spot_bid,
                btc_spot_ask=point.btc_spot_ask,
                contracts=[point.contract],
            )
            if not vol.has_sufficient_data():
                continue
            opportunity = signal_engine.process(snapshot, vol)
            if open_trade is None and opportunity.signals:
                signal = opportunity.signals[0]
                open_trade = {
                    "trade_id": str(uuid.uuid4()),
                    "entry_time": point.timestamp,
                    "entry_spot": point.btc_spot_mid,
                    "entry_contract_price": signal.contract.yes_ask if signal.direction == "buy_yes" else signal.contract.no_ask,
                    "direction": signal.direction,
                    "hedge_btc": abs(signal.hedge_ratio * self._config.KELLY_FRACTION),
                    "model_prob": signal.model_prob,
                    "implied_prob": signal.implied_prob,
                    "edge_bps": signal.edge_bps,
                "notional": self._config.MAX_KALSHI_NOTIONAL_PER_CONTRACT,
                }
                continue
            if open_trade is not None:
                if self._should_exit(open_trade["entry_time"], point.timestamp, point, open_trade["entry_spot"]):
                    exit_contract_price = point.contract.yes_bid if open_trade["direction"] == "buy_yes" else point.contract.no_bid
                    exit_spot = point.btc_spot_mid
                    net_pnl = self._mark_pnl(open_trade, exit_contract_price, exit_spot)
                    trades.append(
                        BacktestTrade(
                            trade_id=open_trade["trade_id"],
                            entry_time=open_trade["entry_time"],
                            exit_time=point.timestamp,
                            contract=point.contract.ticker,
                            direction=open_trade["direction"],
                            entry_spot=float(open_trade["entry_spot"]),
                            exit_spot=exit_spot,
                            entry_contract_price=float(open_trade["entry_contract_price"]),
                            exit_contract_price=exit_contract_price,
                            notional=float(open_trade["notional"]),
                            hedge_btc=float(open_trade["hedge_btc"]),
                            model_prob=float(open_trade["model_prob"]),
                            implied_prob=float(open_trade["implied_prob"]),
                            edge_bps=float(open_trade["edge_bps"]),
                            net_pnl=net_pnl,
                            exit_reason=self._exit_reason(open_trade["entry_spot"], exit_spot, open_trade["entry_time"], point.timestamp),
                        )
                    )
                    open_trade = None
        return trades

    def _mark_pnl(self, trade: dict[str, Any], exit_contract_price: float, exit_spot: float) -> float:
        contract_edge = exit_contract_price - float(trade["entry_contract_price"])
        spot_edge = exit_spot - float(trade["entry_spot"])
        if trade["direction"] == "buy_no":
            contract_pnl = contract_edge
            hedge_pnl = -spot_edge * float(trade["hedge_btc"]) / max(float(trade["entry_spot"]), 1e-9)
        else:
            contract_pnl = -contract_edge
            hedge_pnl = spot_edge * float(trade["hedge_btc"]) / max(float(trade["entry_spot"]), 1e-9)
        return (contract_pnl + hedge_pnl) * float(trade["notional"])

    def _should_exit(self, entry_time: datetime, current_time: datetime, point: HistoricalPoint, entry_spot: float) -> bool:
        dte = (point.contract.expiry_dt - current_time).total_seconds() / 3600.0
        pnl_bps = ((point.btc_spot_mid - entry_spot) / max(entry_spot, 1e-9)) * 10000.0
        return (
            abs(pnl_bps) >= self._config.PROFIT_TARGET_BPS
            or (abs(pnl_bps) >= self._config.STOP_LOSS_BPS and pnl_bps < 0)
            or dte <= 0
            or (current_time - entry_time).total_seconds() >= self._config.TIME_EXIT_HOURS * 3600.0
        )

    def _exit_reason(self, entry_spot: float, exit_spot: float, entry_time: datetime, exit_time: datetime) -> str:
        pnl_bps = ((exit_spot - entry_spot) / max(entry_spot, 1e-9)) * 10000.0
        if abs(pnl_bps) >= self._config.PROFIT_TARGET_BPS:
            return "profit_target"
        if abs(pnl_bps) >= self._config.STOP_LOSS_BPS and pnl_bps < 0:
            return "stop_loss"
        if (exit_time - entry_time).total_seconds() >= self._config.TIME_EXIT_HOURS * 3600.0:
            return "time_exit"
        return "expiry"


async def main() -> int:
    import argparse
    from arbvoy.config import load_config

    parser = argparse.ArgumentParser()
    parser.add_argument("--kalshi-ticker")
    parser.add_argument("--robinhood-history-path")
    args = parser.parse_args()

    config = load_config()
    runner = BacktestRunner(config)
    result = await runner.run(
        kalshi_ticker=args.kalshi_ticker or "KXBTC-26FEB2717-B65750",
        robinhood_history_path=args.robinhood_history_path or "artifacts/robinhood_history.csv"
    )
    print(f"points={len(result.points)} trades={len(result.trades)} report={result.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
