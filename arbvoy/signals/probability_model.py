from __future__ import annotations

import math

try:
    from scipy.stats import norm
except Exception:  # pragma: no cover
    norm = None  # type: ignore[assignment]


class ProbabilityModel:
    @staticmethod
    def _cdf(x: float) -> float:
        if norm is not None:
            return float(norm.cdf(x))
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    @staticmethod
    def _pdf(x: float) -> float:
        if norm is not None:
            return float(norm.pdf(x))
        return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)

    def model_probability(self, spot: float, strike: float, days_to_expiry: float, annualized_vol: float, r: float = 0.0) -> float:
        if days_to_expiry <= 0:
            return 1.0 if spot > strike else 0.0
        t = days_to_expiry / 365.0
        vol = max(annualized_vol, 1e-9)
        d2 = (math.log(spot / strike) + (r - 0.5 * vol * vol) * t) / (vol * math.sqrt(t))
        return math.exp(-r * t) * self._cdf(d2)

    def hedge_ratio(self, spot: float, strike: float, days_to_expiry: float, annualized_vol: float, r: float = 0.0) -> float:
        if days_to_expiry <= 0:
            return 0.0
        t = days_to_expiry / 365.0
        vol = max(annualized_vol, 1e-9)
        d2 = (math.log(spot / strike) + (r - 0.5 * vol * vol) * t) / (vol * math.sqrt(t))
        denom = max(spot * vol * math.sqrt(t), 1e-9)
        return (math.exp(-r * t) * self._pdf(d2)) / denom

