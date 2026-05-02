from __future__ import annotations

from dataclasses import dataclass

from arbvoy.feeds.models import MarketSnapshot
from arbvoy.signals.models import PricingSignal
from arbvoy.strategy.models import RegimeTag, Strategy, StrategyStatus


@dataclass(slots=True)
class StrategySelector:
    def detect_regime(self, snapshot: MarketSnapshot, volatility: float) -> set[RegimeTag]:
        tags: set[RegimeTag] = set()
        tags.add(RegimeTag.HIGH_VOL if volatility >= 0.8 else RegimeTag.LOW_VOL)
        if snapshot.btc_spot_mid >= snapshot.btc_spot_bid:
            tags.add(RegimeTag.TRENDING)
        else:
            tags.add(RegimeTag.RANGING)
        tags.add(RegimeTag.ANY)
        return tags

    def select(self, signal: PricingSignal, strategies: list[Strategy], regime_tags: set[RegimeTag] | None = None) -> Strategy | None:
        candidates = [s for s in strategies if s.status == StrategyStatus.LIVE]
        if regime_tags is not None:
            candidates = [s for s in candidates if RegimeTag.ANY in s.regime_tags or any(tag in regime_tags for tag in s.regime_tags)]
        candidates = [s for s in candidates if s.entry_conditions.direction_filter in ("any", signal.direction)]
        candidates = [s for s in candidates if signal.edge_bps >= s.entry_conditions.min_edge_bps]
        if not candidates:
            return None
        return max(candidates, key=lambda s: s.fitness.composite if s.fitness else 0.0)

