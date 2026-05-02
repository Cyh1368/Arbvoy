from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from arbvoy.evolution.shadow_tester import ShadowTester
from arbvoy.evolution.shinka import ShinkaEvolution
from arbvoy.evolution.fitness import FitnessEvaluator
from arbvoy.evolution.strategy_parser import StrategyParser
from arbvoy.journal.db import JournalDB
from arbvoy.strategy.defaults import SEED_STRATEGY
from arbvoy.strategy.models import EntryConditions, ExitTriggers, RegimeTag, SizingRules, Strategy, StrategyStatus
from arbvoy.strategy.registry import StrategyRegistry
from arbvoy.feeds.models import ContractQuote
from arbvoy.signals.models import PricingSignal, OpportunitySet

from tests.conftest import make_config


class MockClient:
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.calls = 0
        self.messages = SimpleNamespace(create=self.create)

    async def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls += 1
        return SimpleNamespace(content=[SimpleNamespace(text=self.payload)])


def _strategy_dict(name: str = "s") -> dict[str, object]:
    return Strategy(
        strategy_id=name,
        parent_id=None,
        generation=1,
        status=StrategyStatus.LIVE,
        regime_tags=[RegimeTag.ANY],
        entry_conditions=EntryConditions(),
        sizing_rules=SizingRules(),
        exit_triggers=ExitTriggers(),
        mutation_rationale="seed",
    ).model_dump(mode="json")


@pytest.mark.asyncio()
async def test_full_evolution_cycle_creates_shadow_strategies(tmp_path) -> None:
    config = make_config(tmp_path)
    db = JournalDB(str(tmp_path / "evo.db"))
    await db.initialize()
    registry = StrategyRegistry(db)
    await registry.upsert(SEED_STRATEGY)
    await registry.refresh()
    payload = json.dumps([_strategy_dict(f"s{i}") for i in range(4)])
    client = MockClient(payload)
    evolution = ShinkaEvolution(config=config, db=db, strategy_registry=registry, client_factory=lambda: client)
    result = await evolution.run_cycle()
    strategies = await db.list_strategies()
    assert result["shadow"] == 4
    assert len(strategies) == 5
    assert sum(1 for row in strategies if row["status"] == "SHADOW") == 4
    assert client.calls == 1


@pytest.mark.asyncio()
async def test_invalid_json_retries_then_aborts(tmp_path) -> None:
    config = make_config(tmp_path)
    db = JournalDB(str(tmp_path / "evo.db"))
    await db.initialize()
    registry = StrategyRegistry(db)
    await registry.upsert(SEED_STRATEGY)
    await registry.refresh()
    client = MockClient("not-json")
    evolution = ShinkaEvolution(config=config, db=db, strategy_registry=registry, client_factory=lambda: client)
    result = await evolution.run_cycle()
    strategies = await db.list_strategies()
    assert result["shadow"] == 0
    assert len(strategies) == 1
    assert client.calls == 3


@pytest.mark.asyncio()
async def test_shadow_strategy_emits_promotion_candidate(tmp_path) -> None:
    config = make_config(tmp_path)
    db = JournalDB(str(tmp_path / "shadow.db"))
    await db.initialize()
    promotion_queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    tester = ShadowTester(db=db, fitness_evaluator=FitnessEvaluator(), promotion_queue=promotion_queue)
    strategy = Strategy(
        strategy_id="shadow-1",
        parent_id=None,
        generation=1,
        status=StrategyStatus.SHADOW,
        regime_tags=[RegimeTag.ANY],
        entry_conditions=EntryConditions(min_edge_bps=10),
        sizing_rules=SizingRules(),
        exit_triggers=ExitTriggers(),
        mutation_rationale="test",
    )
    contract = ContractQuote(
        ticker="KXBTC-100K",
        strike_usd=100000.0,
        expiry_dt=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        yes_ask=0.42,
        no_ask=0.58,
        yes_bid=0.41,
        no_bid=0.57,
        volume_24h=5000.0,
        open_interest=1000.0,
    )
    signal = PricingSignal(contract=contract, model_prob=0.3, implied_prob=0.42, edge_bps=1200.0, direction="buy_no", hedge_ratio=0.01, spot_at_signal=97000.0)
    queue: asyncio.Queue[OpportunitySet] = asyncio.Queue()
    for _ in range(20):
        await queue.put(OpportunitySet(signals=[signal], spot_price=97000.0, vol_used=0.6))
    await tester.run_shadow_cycle(strategy, queue)
    event = await promotion_queue.get()
    assert event["event"] == "PROMOTION_CANDIDATE"


@pytest.mark.asyncio()
async def test_condemned_strategies_not_archived_below_threshold(tmp_path) -> None:
    config = make_config(tmp_path)
    db = JournalDB(str(tmp_path / "evo.db"))
    await db.initialize()
    registry = StrategyRegistry(db)
    await registry.upsert(SEED_STRATEGY)
    await registry.refresh()
    # Create one live strategy with fewer than 20 trades. It can be scored, but should not be condemned.
    strategy = Strategy(
        strategy_id="live-1",
        parent_id=None,
        generation=1,
        status=StrategyStatus.LIVE,
        regime_tags=[RegimeTag.ANY],
        entry_conditions=EntryConditions(),
        sizing_rules=SizingRules(),
        exit_triggers=ExitTriggers(),
        mutation_rationale="test",
    )
    await registry.upsert(strategy)
    for _ in range(15):
        await db.record_trade_open(
            {
                "trade_id": str(uuid.uuid4()),
                "strategy_id": "live-1",
                "strategy_generation": 1,
                "status": "CLOSED",
                "ticker": "KXBTC-100K",
                "strike_usd": 100000.0,
                "expiry_dt": "2026-01-01T00:00:00Z",
                "direction": "buy_no",
                "kalshi_notional": 100.0,
                "kalshi_fill_price": 0.5,
                "hedge_btc": 0.0,
                "robinhood_fill_price": 97000.0,
                "model_prob": 0.3,
                "implied_prob": 0.42,
                "edge_bps_at_entry": 1200.0,
                "vol_at_entry": 0.6,
                "spot_at_entry": 97000.0,
                "entry_timestamp": "2026-01-01T00:00:00Z",
                "exit_timestamp": "2026-01-01T01:00:00Z",
                "exit_reason": "time_exit",
                "kalshi_pnl": 1.0,
                "robinhood_pnl": 0.0,
                "fees_usd": 0.0,
                "net_pnl": 1.0,
                "slippage_bps": 0.0,
                "snapshot_json": "{}",
            }
        )
    payload = json.dumps([_strategy_dict(f"s{i}") for i in range(4)])
    client = MockClient(payload)
    evolution = ShinkaEvolution(config=config, db=db, strategy_registry=registry, client_factory=lambda: client)
    await evolution.run_cycle()
    rows = await db.get_strategies(status="ARCHIVED")
    assert len(rows) == 0

