from __future__ import annotations

from dataclasses import dataclass, field

from arbvoy.feeds.models import ContractQuote, MarketSnapshot


@dataclass(slots=True)
class PricingSignal:
    contract: ContractQuote
    model_prob: float
    implied_prob: float
    edge_bps: float
    direction: str
    hedge_ratio: float
    spot_at_signal: float


@dataclass(slots=True)
class OpportunitySet:
    signals: list[PricingSignal] = field(default_factory=list)
    snapshot_timestamp: object | None = None
    spot_price: float = 0.0
    vol_used: float = 0.0

