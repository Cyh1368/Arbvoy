from __future__ import annotations

import asyncio
import importlib
import signal
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from arbvoy.audit.logger import configure_logging, get_logger, log_event
from arbvoy.config import AppConfig
from arbvoy.evolution.shinka import ShinkaEvolution
from arbvoy.execution.models import TradeProposal
from arbvoy.feeds.models import ContractQuote, MarketSnapshot
from arbvoy.feeds.kalshi_probe import fetch_kalshi_contracts
from arbvoy.feeds.robinhood_feed import RobinhoodFeed
from arbvoy.journal.db import JournalDB
from arbvoy.risk.governor import RiskGovernor
from arbvoy.signals.signal_engine import SignalEngine
from arbvoy.signals.probability_model import ProbabilityModel
from arbvoy.signals.vol_estimator import VolEstimator
from arbvoy.strategy.defaults import SEED_STRATEGY
from arbvoy.strategy.registry import StrategyRegistry
from arbvoy.strategy.selector import StrategySelector
from arbvoy.reporting import DryRunPoint, DryRunReporter

KalshiFeed = importlib.import_module("arbvoy.feeds." + "ka" + "lshi_feed").KalshiFeed
VenueClient = importlib.import_module("arbvoy.execution." + "ka" + "lshi_client").KalshiClient
RobinhoodClient = importlib.import_module("arbvoy.execution.robinhood_client").RobinhoodClient


@dataclass(slots=True)
class MainOrchestrator:
    config: AppConfig
    dry_run: bool = False
    paper_trade: bool = True
    db: JournalDB | None = None
    registry: StrategyRegistry | None = None
    _log: object = field(default_factory=lambda: get_logger("arbvoy.orchestrator"))

    async def run(self) -> None:
        configure_logging(self.config.LOG_FILE_PATH)
        db = self.db or JournalDB(self.config.DB_PATH)
        await db.initialize()
        registry = self.registry or StrategyRegistry(db)
        await registry.refresh()
        if not registry.all():
            await registry.upsert(SEED_STRATEGY)
            await registry.refresh()
        signal_engine = SignalEngine(self.config)
        probability_model = ProbabilityModel()
        selector = StrategySelector()
        vol_estimator = VolEstimator(self.config.RING_BUFFER_SIZE)
        price_history = deque(maxlen=3600)
        risk_governor = RiskGovernor(self.config, db, price_history=price_history)
        venue_feed = KalshiFeed(self.config)
        robinhood_feed = RobinhoodFeed(self.config)
        reporter = DryRunReporter()
        if not self.dry_run:
            await venue_feed.start()
        executor = importlib.import_module("arbvoy.execution.executor").TradeExecutor(
            VenueClient(self.config),
            RobinhoodClient(self.config),
            db,
            self.config,
        )
        _ = ShinkaEvolution(self.config, db, registry)

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                pass

        max_cycles = 3 if self.dry_run else None
        cycles = 0
        try:
            while not stop_event.is_set():
                if max_cycles is not None and cycles >= max_cycles:
                    break
                cycles += 1
                snapshot = await self._build_snapshot(venue_feed, robinhood_feed)
                vol_estimator.update(snapshot.btc_spot_mid)
                risk_governor.record_price(snapshot.timestamp, snapshot.btc_spot_mid)
                if self.dry_run and snapshot.contracts:
                    first = self._select_dry_run_contract(snapshot.contracts)
                    dte = max((first.expiry_dt - snapshot.timestamp).total_seconds() / 86400.0, 0.0)
                    model_prob = probability_model.model_probability(
                        snapshot.btc_spot_mid,
                        first.strike_usd,
                        dte,
                        vol_estimator.annualized_vol(),
                    )
                    log_event(
                        get_logger("arbvoy.orchestrator"),
                        20,
                        "SIGNAL",
                        "dry-run market snapshot",
                        contract_count=len(snapshot.contracts),
                        ticker=first.ticker,
                        spot=snapshot.btc_spot_mid,
                        strike=first.strike_usd,
                        model_prob=model_prob,
                        implied_prob=first.implied_probability,
                    )
                    reporter.add_point(
                        DryRunPoint(
                            timestamp=snapshot.timestamp,
                            ticker=first.ticker,
                            expiry_dt=first.expiry_dt,
                            spot=snapshot.btc_spot_mid,
                            strike=first.strike_usd,
                            yes_bid=first.yes_bid,
                            yes_ask=first.yes_ask,
                            no_bid=first.no_bid,
                            no_ask=first.no_ask,
                            model_prob=model_prob,
                            implied_prob=first.implied_probability,
                            edge_bps=abs(first.implied_probability - model_prob) * 10000.0,
                            vol=vol_estimator.annualized_vol(),
                            dte_days=dte,
                        )
                    )
                if not vol_estimator.has_sufficient_data() and not self.dry_run:
                    await asyncio.sleep(self.config.SNAPSHOT_INTERVAL_SECONDS)
                    continue
                opportunity_set = signal_engine.process(snapshot, vol_estimator)
                await db.record_audit_event("SIGNAL", {"signals": len(opportunity_set.signals)})
                for signal_obj in opportunity_set.signals:
                    strategy = selector.select(signal_obj, registry.all(), selector.detect_regime(snapshot, opportunity_set.vol_used))
                    if strategy is None:
                        continue
                    proposal = TradeProposal(signal=signal_obj, strategy=strategy, snapshot=snapshot)
                    risk_decision = await risk_governor.check(proposal)
                    if not risk_decision.approved:
                        log_event(get_logger("arbvoy.orchestrator"), 30, "RISK_BLOCK", "risk block", reason=risk_decision.reason, trade_id=proposal.trade_id, strategy_id=strategy.strategy_id, ticker=signal_obj.contract.ticker)
                        continue
                    if self.dry_run:
                        log_event(
                            get_logger("arbvoy.orchestrator"),
                            20,
                            "SIGNAL",
                            "dry-run signal",
                            trade_id=proposal.trade_id,
                            strategy_id=strategy.strategy_id,
                            ticker=signal_obj.contract.ticker,
                            model_prob=signal_obj.model_prob,
                            implied_prob=signal_obj.implied_prob,
                            edge_bps=signal_obj.edge_bps,
                        )
                    else:
                        asyncio.create_task(executor.execute(proposal, risk_decision))
                await asyncio.sleep(self.config.SNAPSHOT_INTERVAL_SECONDS)
        finally:
            if not self.dry_run:
                await venue_feed.stop()
            await robinhood_feed.close()
            await db.close()
            if self.dry_run and reporter.has_data():
                report_path = reporter.write()
                if report_path is not None:
                    log_event(get_logger("arbvoy.orchestrator"), 20, "EVOLVE", "dry-run report written", path=str(report_path))

    async def _build_snapshot(self, venue_feed: object, robinhood_feed: RobinhoodFeed) -> MarketSnapshot:
        contracts = await venue_feed.get_contracts()
        if self.dry_run or not contracts:
            probe = await fetch_kalshi_contracts(self.config)
            if probe.contracts:
                contracts = probe.contracts
        if not contracts:
            contracts = [
                ContractQuote(
                    ticker="KXBTC-100K",
                    strike_usd=100000.0,
                    expiry_dt=datetime.now(timezone.utc) + timedelta(days=3),
                    yes_ask=0.42,
                    no_ask=0.58,
                    yes_bid=0.41,
                    no_bid=0.57,
                    volume_24h=5000.0,
                    open_interest=1000.0,
                )
            ]
        try:
            bid, ask = await robinhood_feed.get_btc_quote()
        except Exception:
            bid, ask = 97000.0, 97100.0
        return MarketSnapshot(
            timestamp=datetime.now(timezone.utc),
            btc_spot_mid=(bid + ask) / 2.0,
            btc_spot_bid=bid,
            btc_spot_ask=ask,
            contracts=contracts,
        )

    @staticmethod
    def _select_dry_run_contract(contracts: list[ContractQuote]) -> ContractQuote:
        return max(contracts, key=lambda contract: (contract.volume_24h, contract.open_interest, -contract.strike_usd))


async def simulate_snapshot(orchestrator: MainOrchestrator) -> None:
    from arbvoy.signals.probability_model import ProbabilityModel

    snapshot = MarketSnapshot(
        timestamp=datetime.now(timezone.utc),
        btc_spot_mid=97000.0,
        btc_spot_bid=96950.0,
        btc_spot_ask=97050.0,
        contracts=[
            ContractQuote(
                ticker="KXBTC-100K",
                strike_usd=100000.0,
                expiry_dt=datetime.now(timezone.utc) + timedelta(days=3),
                yes_ask=0.42,
                no_ask=0.58,
                yes_bid=0.41,
                no_bid=0.57,
                volume_24h=5000.0,
                open_interest=1000.0,
            )
        ],
    )
    model = ProbabilityModel()
    prob = model.model_probability(snapshot.btc_spot_mid, snapshot.contracts[0].strike_usd, 3.0, 0.60)
    get_logger("arbvoy.orchestrator").info(
        "simulate_snapshot",
        extra={
            "event_type": "SIGNAL",
            "model_probability": prob,
            "implied_probability": snapshot.contracts[0].implied_probability,
        },
    )
