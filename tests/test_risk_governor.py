from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone

import pytest

from arbvoy.execution.models import TradeProposal
from arbvoy.feeds.models import ContractQuote, MarketSnapshot
from arbvoy.risk.governor import RiskGovernor
from arbvoy.strategy.models import EntryConditions, ExitTriggers, RegimeTag, SizingRules, Strategy, StrategyStatus
from arbvoy.signals.models import PricingSignal

from tests.conftest import make_config


class MockJournal:
    def __init__(self, daily_pnl: float = 0.0, open_notional: float = 0.0, ticker_notional: float = 0.0, duplicate: bool = False) -> None:
        self.daily_pnl = daily_pnl
        self.open_notional = open_notional
        self.ticker_notional = ticker_notional
        self.duplicate = duplicate

    async def get_daily_pnl(self) -> float:
        return self.daily_pnl

    async def get_open_notional(self) -> float:
        return self.open_notional

    async def get_open_ticker_notional(self, ticker: str) -> float:
        return self.ticker_notional

    async def has_duplicate_open_position(self, ticker: str, direction: str) -> bool:
        return self.duplicate


def _proposal(hedge_ratio: float = 0.01) -> TradeProposal:
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
        model_prob=0.30,
        implied_prob=0.42,
        edge_bps=1200.0,
        direction="buy_no",
        hedge_ratio=hedge_ratio,
        spot_at_signal=97000.0,
    )
    strategy = Strategy(
        strategy_id="s1",
        parent_id=None,
        generation=0,
        status=StrategyStatus.LIVE,
        regime_tags=[RegimeTag.ANY],
        entry_conditions=EntryConditions(),
        sizing_rules=SizingRules(),
        exit_triggers=ExitTriggers(),
        mutation_rationale="seed",
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
async def test_daily_loss_halts(app_config) -> None:
    governor = RiskGovernor(app_config, MockJournal(daily_pnl=-1000.0))
    decision = await governor.check(_proposal())
    assert not decision.approved
    assert decision.reason == "DAILY_LOSS_HALT"


@pytest.mark.asyncio()
async def test_position_limit_blocks(app_config) -> None:
    governor = RiskGovernor(app_config, MockJournal(open_notional=app_config.MAX_TOTAL_KALSHI_NOTIONAL))
    decision = await governor.check(_proposal())
    assert not decision.approved
    assert decision.reason == "POSITION_LIMIT"


@pytest.mark.asyncio()
async def test_circuit_breaker_blocks(app_config) -> None:
    history = deque(maxlen=10)
    governor = RiskGovernor(app_config, MockJournal(), price_history=history)
    governor.record_price(datetime.now(timezone.utc) - timedelta(minutes=16), 100.0)
    governor.record_price(datetime.now(timezone.utc), 106.0)
    decision = await governor.check(_proposal())
    assert not decision.approved
    assert decision.reason == "CIRCUIT_BREAKER"


@pytest.mark.asyncio()
async def test_approved_when_checks_pass(app_config) -> None:
    governor = RiskGovernor(app_config, MockJournal())
    decision = await governor.check(_proposal())
    assert decision.approved
    assert decision.adjusted_notional is not None


@pytest.mark.asyncio()
async def test_hedge_scales_down_when_limit_exceeded(app_config) -> None:
    governor = RiskGovernor(app_config, MockJournal())
    proposal = _proposal(hedge_ratio=1.0)
    decision = await governor.check(proposal)
    assert decision.approved
    assert decision.adjusted_notional is not None
    assert decision.adjusted_notional < proposal.strategy.sizing_rules.base_notional_usd * proposal.strategy.sizing_rules.kelly_fraction

