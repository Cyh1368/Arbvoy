from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List


@dataclass(slots=True)
class ContractQuote:
    ticker: str
    strike_usd: float
    expiry_dt: datetime
    yes_ask: float
    no_ask: float
    yes_bid: float
    no_bid: float
    volume_24h: float
    open_interest: float
    cap_strike_usd: float | None = None

    @property
    def implied_probability(self) -> float:
        return self.yes_ask

    @property
    def spread_arb_score(self) -> float:
        return 1.0 - (self.yes_ask + self.no_ask)


@dataclass(slots=True)
class MarketSnapshot:
    timestamp: datetime
    btc_spot_mid: float
    btc_spot_bid: float
    btc_spot_ask: float
    contracts: list[ContractQuote] = field(default_factory=list)

