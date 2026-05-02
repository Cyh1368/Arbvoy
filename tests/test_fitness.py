from __future__ import annotations

import uuid

import pytest

from arbvoy.evolution.fitness import FitnessEvaluator
from arbvoy.journal.db import JournalDB

from tests.conftest import make_config


async def _insert_trade(db: JournalDB, strategy_id: str, net_pnl: float, kalshi_notional: float = 100.0) -> None:
    await db.record_trade_open(
        {
            "trade_id": str(uuid.uuid4()),
            "strategy_id": strategy_id,
            "strategy_generation": 1,
            "status": "CLOSED",
            "ticker": "KXBTC-100K",
            "strike_usd": 100000.0,
            "expiry_dt": "2026-01-01T00:00:00Z",
            "direction": "buy_no",
            "kalshi_notional": kalshi_notional,
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
            "exit_reason": "profit_target",
            "kalshi_pnl": net_pnl,
            "robinhood_pnl": 0.0,
            "fees_usd": 0.0,
            "net_pnl": net_pnl,
            "slippage_bps": 0.0,
            "snapshot_json": "{}",
        }
    )


@pytest.mark.asyncio()
async def test_returns_none_when_too_few_trades(tmp_path) -> None:
    db = JournalDB(str(tmp_path / "fitness.db"))
    await db.initialize()
    evaluator = FitnessEvaluator()
    assert await evaluator.evaluate("s1", db) is None


@pytest.mark.asyncio()
async def test_sharpe_zero_when_break_even(tmp_path) -> None:
    db = JournalDB(str(tmp_path / "fitness.db"))
    await db.initialize()
    for _ in range(10):
        await _insert_trade(db, "s1", 0.0)
    evaluator = FitnessEvaluator()
    score = await evaluator.evaluate("s1", db)
    assert score is not None
    assert score.sharpe == 0.0
    assert 0.0 <= score.composite <= 1.0


@pytest.mark.asyncio()
async def test_better_strategy_scores_higher(tmp_path) -> None:
    db = JournalDB(str(tmp_path / "fitness.db"))
    await db.initialize()
    for _ in range(10):
        await _insert_trade(db, "worse", -1.0)
    for _ in range(10):
        await _insert_trade(db, "better", 5.0)
    evaluator = FitnessEvaluator()
    worse = await evaluator.evaluate("worse", db)
    better = await evaluator.evaluate("better", db)
    assert worse is not None and better is not None
    assert better.composite > worse.composite

