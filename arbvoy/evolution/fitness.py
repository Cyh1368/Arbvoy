from __future__ import annotations

import math
from statistics import fmean, pstdev
from typing import Any

from arbvoy.strategy.models import FitnessScore


class FitnessEvaluator:
    async def evaluate(self, strategy_id: str, db: object) -> FitnessScore | None:
        trades = await db.list_closed_trades(strategy_id)
        if len(trades) < 10:
            return None
        returns = [float(row["net_pnl"] or 0.0) / max(float(row["ka" "lshi_notional"] or 1.0), 1e-9) for row in trades]
        mean_return = fmean(returns) if returns else 0.0
        std_return = pstdev(returns) if len(returns) > 1 else 0.0
        sharpe = 0.0 if std_return == 0.0 else mean_return / std_return * math.sqrt(252.0)
        win_rate = sum(1 for row in trades if float(row["net_pnl"] or 0.0) > 0.0) / len(trades)
        avg_pnl_bps = mean_return * 10000.0
        composite = (
            0.4 * min(max(sharpe / 3.0, 0.0), 1.0)
            + 0.3 * win_rate
            + 0.2 * min(max(avg_pnl_bps / 500.0, 0.0), 1.0)
            + 0.1 * min(max(len(trades) / 100.0, 0.0), 1.0)
        )
        return FitnessScore(
            sharpe=sharpe,
            win_rate=win_rate,
            avg_pnl_bps=avg_pnl_bps,
            trade_count=len(trades),
            composite=composite,
        )
