from __future__ import annotations

from datetime import datetime, timezone

from arbvoy.strategy.models import EntryConditions, ExitTriggers, RegimeTag, SizingRules, Strategy, StrategyStatus


SEED_STRATEGY = Strategy(
    strategy_id="",
    parent_id=None,
    generation=0,
    status=StrategyStatus.LIVE,
    regime_tags=[RegimeTag.ANY],
    entry_conditions=EntryConditions(),
    sizing_rules=SizingRules(),
    exit_triggers=ExitTriggers(),
    mutation_rationale="Seed strategy - human authored",
    created_at=datetime.now(timezone.utc),
).with_generated_id()

