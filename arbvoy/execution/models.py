from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from arbvoy.feeds.models import MarketSnapshot
from arbvoy.signals.models import PricingSignal
from arbvoy.strategy.models import Strategy


class OrderState(str, Enum):
    IDLE = "IDLE"
    LEG1_PENDING = "LEG1_PENDING"
    LEG1_FILLED = "LEG1_FILLED"
    LEG2_PENDING = "LEG2_PENDING"
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    FAILED = "FAILED"


@dataclass(slots=True)
class TradeProposal:
    signal: PricingSignal
    strategy: Strategy
    snapshot: MarketSnapshot
    trade_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass(slots=True)
class Fill:
    order_id: str
    price: float
    quantity: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "FILLED"


@dataclass(slots=True)
class TradeResult:
    trade_id: str
    state: OrderState
    venue_fill_price: float | None = None
    robinhood_fill_price: float | None = None
    hedge_btc: float | None = None
    net_pnl: float | None = None
    exit_reason: str | None = None
