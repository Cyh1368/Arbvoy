from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Deque, Protocol

from arbvoy.audit.logger import get_logger
from arbvoy.config import AppConfig
from arbvoy.feeds.models import MarketSnapshot
from arbvoy.execution.models import TradeProposal


@dataclass(slots=True)
class RiskDecision:
    approved: bool
    reason: str | None
    adjusted_notional: float | None


class _JournalLike(Protocol):
    async def get_daily_pnl(self) -> float: ...
    async def get_open_notional(self) -> float: ...
    async def get_open_ticker_notional(self, ticker: str) -> float: ...
    async def has_duplicate_open_position(self, ticker: str, direction: str) -> bool: ...


class RiskGovernor:
    def __init__(self, config: AppConfig, journal: _JournalLike, price_history: Deque[tuple[datetime, float]] | None = None) -> None:
        self._config = config
        self._journal = journal
        self._price_history = price_history or deque(maxlen=3600)
        self._log = get_logger("arbvoy.risk.governor")

    def record_price(self, timestamp: datetime, price: float) -> None:
        self._price_history.append((timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc), float(price)))

    async def check(self, proposal: TradeProposal) -> RiskDecision:
        daily_pnl = await self._journal.get_daily_pnl()
        capital = max(self._config.MAX_TOTAL_KALSHI_NOTIONAL * 10.0, 10000.0)
        if daily_pnl < -(capital * self._config.DAILY_LOSS_LIMIT_PCT):
            return RiskDecision(False, "DAILY_LOSS_HALT", None)

        open_notional = await self._journal.get_open_notional()
        if open_notional >= self._config.MAX_TOTAL_KALSHI_NOTIONAL:
            return RiskDecision(False, "POSITION_LIMIT", None)

        open_ticker_notional = await self._journal.get_open_ticker_notional(proposal.signal.contract.ticker)
        if open_ticker_notional >= self._config.MAX_KALSHI_NOTIONAL_PER_CONTRACT:
            return RiskDecision(False, "CONTRACT_LIMIT", None)

        adjusted = min(
            proposal.strategy.sizing_rules.base_notional_usd * proposal.strategy.sizing_rules.kelly_fraction,
            proposal.strategy.sizing_rules.max_notional_usd,
            self._config.MAX_KALSHI_NOTIONAL_PER_CONTRACT,
        )
        hedge_notional = abs(adjusted * proposal.signal.hedge_ratio * proposal.signal.spot_at_signal)
        if hedge_notional > self._config.MAX_ROBINHOOD_HEDGE_NOTIONAL:
            scale = self._config.MAX_ROBINHOOD_HEDGE_NOTIONAL / max(hedge_notional, 1e-9)
            adjusted *= scale
            adjusted = min(adjusted, self._config.MAX_KALSHI_NOTIONAL_PER_CONTRACT)

        if self._circuit_breaker_active():
            return RiskDecision(False, "CIRCUIT_BREAKER", None)

        if proposal.signal.contract.volume_24h < proposal.strategy.entry_conditions.min_volume_24h:
            return RiskDecision(False, "MIN_LIQUIDITY", None)

        if await self._journal.has_duplicate_open_position(proposal.signal.contract.ticker, proposal.signal.direction):
            return RiskDecision(False, "DUPLICATE", None)

        return RiskDecision(True, None, adjusted)

    def _circuit_breaker_active(self) -> bool:
        if len(self._price_history) < 2:
            return False
        latest_ts, latest_price = self._price_history[-1]
        cutoff = latest_ts.timestamp() - 15.0 * 60.0
        older_price = None
        for ts, price in reversed(self._price_history):
            if ts.timestamp() <= cutoff:
                older_price = price
                break
        if older_price is None:
            return False
        move = abs(latest_price - older_price) / max(older_price, 1e-9)
        return move >= 0.05
