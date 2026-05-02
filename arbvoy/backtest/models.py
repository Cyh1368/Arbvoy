from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from arbvoy.feeds.models import ContractQuote
from arbvoy.signals.models import PricingSignal
from arbvoy.strategy.models import Strategy


@dataclass(slots=True)
class HistoricalPoint:
    timestamp: datetime
    btc_spot_mid: float
    btc_spot_bid: float
    btc_spot_ask: float
    contract: ContractQuote
    model_prob: float | None = None
    implied_prob: float | None = None
    edge_bps: float | None = None
    hours_to_expiry: float | None = None
    vol: float | None = None


@dataclass(slots=True)
class BacktestTrade:
    trade_id: str
    entry_time: datetime
    exit_time: datetime | None
    contract: str
    direction: str
    entry_spot: float
    exit_spot: float | None
    entry_contract_price: float
    exit_contract_price: float | None
    notional: float
    hedge_btc: float
    model_prob: float
    implied_prob: float
    edge_bps: float
    net_pnl: float | None
    exit_reason: str | None
