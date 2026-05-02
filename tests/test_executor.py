from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from arbvoy.config import AppConfig
from arbvoy.execution.executor import TradeExecutor
from arbvoy.execution.models import OrderState, TradeProposal
from arbvoy.feeds.models import ContractQuote, MarketSnapshot
from arbvoy.risk.governor import RiskDecision
from arbvoy.strategy.models import EntryConditions, ExitTriggers, RegimeTag, SizingRules, Strategy, StrategyStatus
from arbvoy.signals.models import PricingSignal

from tests.conftest import make_config


class MockJournal:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []
        self.updated: list[tuple[str, dict[str, object]]] = []

    async def record_trade_open(self, payload: dict[str, object]) -> None:
        self.rows.append(payload)

    async def update_trade(self, trade_id: str, updates: dict[str, object]) -> None:
        self.updated.append((trade_id, updates))


def _proposal() -> TradeProposal:
    contract = ContractQuote(
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
    signal = PricingSignal(
        contract=contract,
        model_prob=0.3,
        implied_prob=0.42,
        edge_bps=1200.0,
        direction="buy_no",
        hedge_ratio=0.01,
        spot_at_signal=97000.0,
    )
    strategy = Strategy(
        strategy_id="s1",
        parent_id=None,
        generation=1,
        status=StrategyStatus.LIVE,
        regime_tags=[RegimeTag.ANY],
        entry_conditions=EntryConditions(),
        sizing_rules=SizingRules(),
        exit_triggers=ExitTriggers(),
        mutation_rationale="test",
    )
    snapshot = MarketSnapshot(
        timestamp=datetime.now(timezone.utc),
        btc_spot_mid=97000.0,
        btc_spot_bid=96950.0,
        btc_spot_ask=97050.0,
        contracts=[contract],
    )
    return TradeProposal(signal=signal, strategy=strategy, snapshot=snapshot)


@pytest.mark.asyncio()
async def test_kalshi_timeout_fails_without_robinhood_order(app_config) -> None:
    journal = MockJournal()
    kalshi = SimpleNamespace(
        submit_order=AsyncMock(return_value={"order_id": "o1"}),
        poll_order=AsyncMock(return_value={"status": "PENDING"}),
        cancel_order=AsyncMock(),
        close_position=AsyncMock(),
    )
    robinhood = SimpleNamespace(submit_order=AsyncMock())
    executor = TradeExecutor(kalshi, robinhood, journal, app_config, price_provider=lambda proposal: (100000.0, 0.42))
    result = await executor.execute(_proposal(), RiskDecision(True, None, 50.0))
    assert result.state == OrderState.FAILED
    robinhood.submit_order.assert_not_awaited()


@pytest.mark.asyncio()
async def test_hedge_failure_triggers_emergency_close(app_config) -> None:
    journal = MockJournal()
    kalshi = SimpleNamespace(
        submit_order=AsyncMock(return_value={"order_id": "o1"}),
        poll_order=AsyncMock(side_effect=[{"status": "FILLED", "filled_notional": 50.0}]),
        cancel_order=AsyncMock(),
        close_position=AsyncMock(),
    )
    robinhood = SimpleNamespace(submit_order=AsyncMock(side_effect=RuntimeError("boom")))
    executor = TradeExecutor(kalshi, robinhood, journal, app_config, price_provider=lambda proposal: (100000.0, 0.42))
    result = await executor.execute(_proposal(), RiskDecision(True, None, 50.0))
    assert result.state == OrderState.FAILED
    kalshi.close_position.assert_awaited()


@pytest.mark.asyncio()
async def test_successful_round_trip_closes_trade(app_config) -> None:
    journal = MockJournal()
    kalshi = SimpleNamespace(
        submit_order=AsyncMock(return_value={"order_id": "o1"}),
        poll_order=AsyncMock(return_value={"status": "FILLED", "filled_notional": 50.0}),
        cancel_order=AsyncMock(),
        close_position=AsyncMock(),
        get_contract_quote=AsyncMock(return_value=SimpleNamespace(yes_ask=0.35)),
    )
    robinhood = SimpleNamespace(submit_order=AsyncMock(return_value={"order_id": "r1", "filled_price": 97000.0}), get_btc_quote=AsyncMock(return_value=(102000.0, 102100.0)))
    executor = TradeExecutor(kalshi, robinhood, journal, app_config, price_provider=lambda proposal: (proposal.signal.spot_at_signal * 1.06, 0.35))
    result = await executor.execute(_proposal(), RiskDecision(True, None, 50.0))
    assert result.state == OrderState.CLOSED
    assert result.net_pnl == 0.0


@pytest.mark.asyncio()
async def test_stop_loss_exit_triggers(app_config) -> None:
    journal = MockJournal()
    kalshi = SimpleNamespace(
        submit_order=AsyncMock(return_value={"order_id": "o1"}),
        poll_order=AsyncMock(return_value={"status": "FILLED", "filled_notional": 50.0}),
        cancel_order=AsyncMock(),
        close_position=AsyncMock(),
        get_contract_quote=AsyncMock(return_value=SimpleNamespace(yes_ask=0.35)),
    )
    robinhood = SimpleNamespace(submit_order=AsyncMock(return_value={"order_id": "r1", "filled_price": 97000.0}), get_btc_quote=AsyncMock(return_value=(95000.0, 95100.0)))
    executor = TradeExecutor(kalshi, robinhood, journal, app_config, price_provider=lambda proposal: (proposal.signal.spot_at_signal * 0.98, 0.35))
    result = await executor.execute(_proposal(), RiskDecision(True, None, 50.0))
    assert result.state == OrderState.CLOSED
    assert result.exit_reason == "stop_loss"

