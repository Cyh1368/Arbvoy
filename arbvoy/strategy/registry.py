from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from arbvoy.journal.db import JournalDB
from arbvoy.strategy.models import FitnessScore, Strategy, StrategyStatus


@dataclass(slots=True)
class StrategyRegistry:
    db: JournalDB
    _strategies: dict[str, Strategy] = field(default_factory=dict)

    async def refresh(self) -> None:
        rows = await self.db.list_strategies()
        self._strategies = {row["strategy_id"]: Strategy.model_validate_json(row["strategy_json"]) for row in rows}

    async def upsert(self, strategy: Strategy) -> None:
        await self.db.upsert_strategy(strategy)
        self._strategies[strategy.strategy_id] = strategy

    def all(self) -> list[Strategy]:
        return list(self._strategies.values())

    def live(self) -> list[Strategy]:
        return [s for s in self._strategies.values() if s.status == StrategyStatus.LIVE]

    def shadow(self) -> list[Strategy]:
        return [s for s in self._strategies.values() if s.status == StrategyStatus.SHADOW]

    def archived(self) -> list[Strategy]:
        return [s for s in self._strategies.values() if s.status == StrategyStatus.ARCHIVED]

    def rank_by_fitness(self, strategies: Iterable[Strategy] | None = None) -> list[Strategy]:
        pool = list(strategies) if strategies is not None else self.all()
        return sorted(pool, key=lambda s: s.fitness.composite if s.fitness else -1.0, reverse=True)

    async def promote(self, strategy_id: str) -> None:
        strategy = self._strategies[strategy_id]
        strategy = strategy.model_copy(update={"status": StrategyStatus.LIVE})
        await self.upsert(strategy)

    async def archive(self, strategy_id: str) -> None:
        strategy = self._strategies[strategy_id]
        strategy = strategy.model_copy(update={"status": StrategyStatus.ARCHIVED})
        await self.upsert(strategy)

