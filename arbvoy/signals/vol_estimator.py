from __future__ import annotations

import math
from collections import deque
from typing import Deque


class VolEstimator:
    def __init__(self, ring_buffer_size: int) -> None:
        self._prices: Deque[float] = deque(maxlen=ring_buffer_size)

    def update(self, price: float) -> None:
        self._prices.append(float(price))

    def has_sufficient_data(self) -> bool:
        return len(self._prices) >= 300

    def annualized_vol(self) -> float:
        if len(self._prices) < 2:
            return 0.30
        returns = [math.log(self._prices[i] / self._prices[i - 1]) for i in range(1, len(self._prices)) if self._prices[i - 1] > 0]
        if not returns:
            return 0.30
        lam = 0.94
        weights = []
        var = 0.0
        for i, r in enumerate(reversed(returns)):
            w = (1.0 - lam) * (lam**i)
            weights.append(w)
            var += w * (r * r)
        total_weight = sum(weights) or 1.0
        ew_var = var / total_weight
        vol_1s = math.sqrt(max(ew_var, 0.0))
        vol_annual = vol_1s * math.sqrt(365.0 * 24.0 * 3600.0)
        return max(0.30, min(vol_annual, 2.50))

