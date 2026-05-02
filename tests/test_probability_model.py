from __future__ import annotations

from arbvoy.signals.probability_model import ProbabilityModel


def test_atm_call_is_about_half() -> None:
    model = ProbabilityModel()
    prob = model.model_probability(spot=100000.0, strike=100000.0, days_to_expiry=7.0, annualized_vol=0.6)
    assert 0.49 <= prob <= 0.51


def test_deep_itm_and_otm() -> None:
    model = ProbabilityModel()
    assert model.model_probability(110000.0, 100000.0, 1.0, 0.8) > 0.90
    assert model.model_probability(90000.0, 100000.0, 1.0, 0.8) < 0.10


def test_expiry_edge_cases() -> None:
    model = ProbabilityModel()
    assert model.model_probability(101.0, 100.0, 0.0, 0.5) == 1.0
    assert model.model_probability(99.0, 100.0, 0.0, 0.5) == 0.0


def test_hedge_ratio_is_positive_and_bounded() -> None:
    model = ProbabilityModel()
    hedge = model.hedge_ratio(spot=100000.0, strike=100000.0, days_to_expiry=7.0, annualized_vol=0.6)
    assert 0.0 < hedge < 1.0

