from __future__ import annotations

import json
from dataclasses import dataclass
from statistics import fmean
from typing import Any

from arbvoy.strategy.models import Strategy


SYSTEM_PROMPT = """You are a quantitative trading strategy optimizer for a Bitcoin prediction market
arbitrage system. You identify why trading strategies underperform and generate
improved variants. You must respond with ONLY a valid JSON array of exactly 4
Strategy objects matching the schema provided. No prose, no markdown, no explanation
outside the JSON. Each object must include a mutation_rationale field explaining
your reasoning in 1-2 sentences."""


class PromptBundle(str):
    def __new__(cls, text: str, system: str, user: str) -> "PromptBundle":
        obj = str.__new__(cls, text)
        obj.system = system  # type: ignore[attr-defined]
        obj.user = user  # type: ignore[attr-defined]
        return obj


class PromptBuilder:
    async def build(self, db: object, strategy_registry: object) -> PromptBundle:
        closed_trades = await db.list_trades(status="CLOSED")
        recent = closed_trades[-200:]
        fitness_rows = []
        for strategy in strategy_registry.all():
            fitness_rows.append(
                {
                    "strategy_id": strategy.strategy_id,
                    "generation": strategy.generation,
                    "status": strategy.status.value,
                    "fitness": None if strategy.fitness is None else strategy.fitness.model_dump(mode="json"),
                }
            )
        live = [s for s in strategy_registry.all() if s.status.value == "LIVE"]
        worst = sorted(live, key=lambda s: s.fitness.composite if s.fitness else -1.0)[:2]
        best = sorted(live, key=lambda s: s.fitness.composite if s.fitness else -1.0, reverse=True)[:3]
        avg_vol = fmean([float(row["vol_at_entry"] or 0.0) for row in recent]) if recent else 0.0
        avg_edge = fmean([float(row["edge_bps_at_entry"] or 0.0) for row in recent]) if recent else 0.0
        trade_freq = float(len(recent))
        payload = {
            "task": "Generate 4 improved strategies: 3 mutations of the worst performers, 1 novel.",
            "strategy_schema": Strategy.model_json_schema(),
            "regime_context": {
                "avg_vol_30d": avg_vol,
                "avg_edge_bps": avg_edge,
                "trade_freq_per_day": trade_freq,
            },
            "worst_strategies": [json.loads(s.model_dump_json()) for s in worst],
            "elite_strategies": [json.loads(s.model_dump_json()) for s in best],
            "recent_trade_summary": {
                "total_trades": len(recent),
                "win_rate": (
                    sum(1 for row in recent if float(row["net_pnl"] or 0.0) > 0.0) / len(recent)
                    if recent
                    else 0.0
                ),
                "avg_pnl_bps": fmean([float(row["net_pnl"] or 0.0) for row in recent]) if recent else 0.0,
                "worst_exit_reasons": self._worst_exit_reasons(recent),
            },
            "fitness_summary": fitness_rows,
        }
        user = json.dumps(payload, default=str)
        return PromptBundle(user, SYSTEM_PROMPT, user)

    @staticmethod
    def _worst_exit_reasons(trades: list[object]) -> list[str]:
        reasons: dict[str, int] = {}
        for row in trades:
            if isinstance(row, dict):
                reason = str(row.get("exit_reason") or "")
            else:
                reason = str(row["exit_reason"] or "")  # type: ignore[index]
            if reason:
                reasons[reason] = reasons.get(reason, 0) + 1
        return [reason for reason, _ in sorted(reasons.items(), key=lambda item: item[1], reverse=True)[:5]]

