from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrategyStatus(str, Enum):
    SHADOW = "SHADOW"
    LIVE = "LIVE"
    ARCHIVED = "ARCHIVED"


class RegimeTag(str, Enum):
    HIGH_VOL = "HIGH_VOL"
    LOW_VOL = "LOW_VOL"
    TRENDING = "TRENDING"
    RANGING = "RANGING"
    ANY = "ANY"


class EntryConditions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_edge_bps: int = 300
    min_days_to_expiry: float = 0.5
    max_days_to_expiry: float = 7.0
    min_volume_24h: float = 1000.0
    direction_filter: str = "any"


class SizingRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_notional_usd: float = 200.0
    kelly_fraction: float = 0.25
    max_notional_usd: float = 500.0


class ExitTriggers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profit_target_bps: int = 300
    stop_loss_bps: int = 150
    time_exit_hours: float = 24.0


class FitnessScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sharpe: float
    win_rate: float
    avg_pnl_bps: float
    trade_count: int
    composite: float


class Strategy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_id: str = ""
    parent_id: str | None = None
    generation: int
    status: StrategyStatus = StrategyStatus.SHADOW
    regime_tags: list[RegimeTag]
    entry_conditions: EntryConditions
    sizing_rules: SizingRules
    exit_triggers: ExitTriggers
    fitness: FitnessScore | None = None
    mutation_rationale: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def make_id(cls, created_at: datetime, parent_id: str | None) -> str:
        seed = f"{created_at.isoformat()}:{parent_id or ''}".encode("utf-8")
        return hashlib.sha256(seed).hexdigest()[:12]

    def with_generated_id(self) -> "Strategy":
        created_at = self.created_at if self.created_at.tzinfo else self.created_at.replace(tzinfo=timezone.utc)
        return self.model_copy(update={"strategy_id": self.make_id(created_at, self.parent_id)})
