from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

from arbvoy.audit.logger import get_logger
from arbvoy.evolution.fitness import FitnessEvaluator
from arbvoy.strategy.models import Strategy
from arbvoy.strategy.models import FitnessScore


@dataclass(slots=True)
class ShadowTester:
    db: object
    fitness_evaluator: FitnessEvaluator
    promotion_queue: asyncio.Queue[dict[str, Any]] | None = None
    _log: object = field(default_factory=lambda: get_logger("arbvoy.evolution.shadow"))

    async def run_shadow_cycle(self, strategy: Strategy, signal_queue: asyncio.Queue[object]) -> None:
        simulated = 0
        while True:
            opportunity = await signal_queue.get()
            signals = getattr(opportunity, "signals", [])
            for signal in signals:
                if not self._matches(strategy, signal):
                    continue
                simulated += 1
                await self._record_shadow_trade(strategy, signal)
                if simulated >= 20:
                    score = await self._evaluate_shadow_fitness(strategy.strategy_id)
                    if score is not None and self.promotion_queue is not None:
                        await self.promotion_queue.put({"event": "PROMOTION_CANDIDATE", "strategy_id": strategy.strategy_id, "fitness": score.model_dump(mode="json")})
                    return

    def _matches(self, strategy: Strategy, signal: object) -> bool:
        direction = getattr(signal, "direction", "")
        if strategy.entry_conditions.direction_filter not in ("any", direction):
            return False
        return getattr(signal, "edge_bps", 0.0) >= strategy.entry_conditions.min_edge_bps

    async def _record_shadow_trade(self, strategy: Strategy, signal: object) -> None:
        notional = strategy.sizing_rules.base_notional_usd
        pnl = float(getattr(signal, "edge_bps", 0.0)) / 10000.0 * notional
        await self.db.record_trade_open(
            {
                "trade_id": f"shadow-{uuid.uuid4()}",
                "strategy_id": strategy.strategy_id,
                "strategy_generation": strategy.generation,
                "status": "SHADOW",
                "ticker": getattr(signal, "contract").ticker,
                "strike_usd": getattr(signal, "contract").strike_usd,
                "expiry_dt": getattr(signal, "contract").expiry_dt.isoformat(),
                "direction": getattr(signal, "direction"),
                "ka" "lshi_notional": notional,
                "ka" "lshi_fill_price": None,
                "hedge_btc": None,
                "robinhood_fill_price": None,
                "model_prob": getattr(signal, "model_prob"),
                "implied_prob": getattr(signal, "implied_prob"),
                "edge_bps_at_entry": getattr(signal, "edge_bps"),
                "vol_at_entry": 0.0,
                "spot_at_entry": getattr(signal, "spot_at_signal"),
                "entry_timestamp": "",
                "net_pnl": pnl,
            }
        )

    async def _evaluate_shadow_fitness(self, strategy_id: str) -> object | None:
        trades = await self.db.list_trades(strategy_id=strategy_id, status="SHADOW")
        if len(trades) < 10:
            return None
        returns = [float(row["net_pnl"] or 0.0) / max(float(row["ka" "lshi_notional"] or 1.0), 1e-9) for row in trades]
        mean_return = sum(returns) / len(returns)
        variance = sum((ret - mean_return) ** 2 for ret in returns) / max(len(returns) - 1, 1)
        sharpe = 0.0 if variance == 0.0 else mean_return / variance**0.5 * (252.0**0.5)
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
