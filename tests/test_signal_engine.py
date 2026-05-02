from __future__ import annotations

from datetime import datetime, timedelta, timezone

from arbvoy.feeds.models import ContractQuote, MarketSnapshot
from arbvoy.signals.signal_engine import SignalEngine
from arbvoy.signals.vol_estimator import VolEstimator

from tests.conftest import make_config


def _snapshot(edge: float = 0.42, volume: float = 5000.0) -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=datetime.now(timezone.utc),
        btc_spot_mid=97000.0,
        btc_spot_bid=96950.0,
        btc_spot_ask=97050.0,
        contracts=[
            ContractQuote(
                ticker="KXBTC-100K",
                strike_usd=100000.0,
                expiry_dt=datetime.now(timezone.utc) + timedelta(days=3),
                yes_ask=edge,
                no_ask=1.0 - edge,
                yes_bid=edge - 0.01,
                no_bid=1.0 - edge - 0.01,
                volume_24h=volume,
                open_interest=1000.0,
            )
        ],
    )


def test_signal_emitted_on_large_edge(app_config) -> None:
    engine = SignalEngine(app_config)
    vol = VolEstimator(app_config.RING_BUFFER_SIZE)
    vol.annualized_vol = lambda: 0.6  # type: ignore[method-assign]
    result = engine.process(_snapshot(edge=0.42), vol)
    assert len(result.signals) == 1
    assert result.signals[0].direction == "buy_no"
    assert result.signals[0].edge_bps > 1000.0


def test_no_signal_below_volume_threshold(app_config) -> None:
    engine = SignalEngine(app_config)
    vol = VolEstimator(app_config.RING_BUFFER_SIZE)
    vol.annualized_vol = lambda: 0.6  # type: ignore[method-assign]
    result = engine.process(_snapshot(volume=10.0), vol)
    assert result.signals == []


def test_no_signal_when_expired(app_config) -> None:
    engine = SignalEngine(app_config)
    vol = VolEstimator(app_config.RING_BUFFER_SIZE)
    vol.annualized_vol = lambda: 0.6  # type: ignore[method-assign]
    snap = _snapshot()
    snap.contracts[0].expiry_dt = datetime.now(timezone.utc) - timedelta(seconds=1)
    result = engine.process(snap, vol)
    assert result.signals == []


def test_direction_buy_yes_when_model_above_implied(app_config) -> None:
    engine = SignalEngine(app_config)
    vol = VolEstimator(app_config.RING_BUFFER_SIZE)
    vol.annualized_vol = lambda: 0.6  # type: ignore[method-assign]
    snap = _snapshot(edge=0.10)
    result = engine.process(snap, vol)
    assert result.signals[0].direction == "buy_yes"

