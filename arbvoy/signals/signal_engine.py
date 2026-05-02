from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from arbvoy.config import AppConfig
from arbvoy.feeds.models import MarketSnapshot
from arbvoy.signals.models import OpportunitySet, PricingSignal
from arbvoy.signals.probability_model import ProbabilityModel
from arbvoy.signals.vol_estimator import VolEstimator


class SignalEngine:
    def __init__(self, config: AppConfig, probability_model: ProbabilityModel | None = None) -> None:
        self._config = config
        self._model = probability_model or ProbabilityModel()

    def process(self, snapshot: MarketSnapshot, vol_estimator: VolEstimator) -> OpportunitySet:
        vol = vol_estimator.annualized_vol()
        signals: list[PricingSignal] = []
        for contract in snapshot.contracts:
            dte = (self._as_utc(contract.expiry_dt) - self._as_utc(snapshot.timestamp)).total_seconds() / 86400.0
            if dte <= 0 or contract.volume_24h < self._config.MIN_KALSHI_VOLUME_24H:
                continue
            model_prob = self._model.model_probability(snapshot.btc_spot_mid, contract.strike_usd, dte, vol)
            implied_prob = contract.implied_probability
            edge_bps = abs(implied_prob - model_prob) * 10000.0
            if edge_bps < self._config.MIN_EDGE_BPS:
                continue
            direction = "buy_no" if implied_prob > model_prob else "buy_yes"
            hedge_ratio = self._model.hedge_ratio(snapshot.btc_spot_mid, contract.strike_usd, dte, vol)
            if direction == "buy_yes":
                hedge_ratio = -hedge_ratio
            signals.append(
                PricingSignal(
                    contract=contract,
                    model_prob=model_prob,
                    implied_prob=implied_prob,
                    edge_bps=edge_bps,
                    direction=direction,
                    hedge_ratio=hedge_ratio,
                    spot_at_signal=snapshot.btc_spot_mid,
                )
            )
        return OpportunitySet(
            signals=signals,
            snapshot_timestamp=snapshot.timestamp,
            spot_price=snapshot.btc_spot_mid,
            vol_used=vol,
        )

    @staticmethod
    def _as_utc(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

