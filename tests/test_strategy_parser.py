from __future__ import annotations

from datetime import datetime, timezone

import pytest

from arbvoy.evolution.strategy_parser import StrategyParser
from arbvoy.exceptions import StrategyParseError
from arbvoy.strategy.models import EntryConditions, ExitTriggers, RegimeTag, SizingRules, Strategy, StrategyStatus


def _valid_strategy_dict() -> dict[str, object]:
    return Strategy(
        strategy_id="old-id",
        parent_id=None,
        generation=1,
        status=StrategyStatus.LIVE,
        regime_tags=[RegimeTag.ANY],
        entry_conditions=EntryConditions(),
        sizing_rules=SizingRules(),
        exit_triggers=ExitTriggers(),
        mutation_rationale="test",
        created_at=datetime.now(timezone.utc),
    ).model_dump(mode="json")


def test_rejects_non_json() -> None:
    parser = StrategyParser()
    with pytest.raises(StrategyParseError):
        parser.parse("not json")


def test_rejects_wrong_list_size() -> None:
    parser = StrategyParser()
    with pytest.raises(StrategyParseError):
        parser.parse("[]")


def test_rejects_missing_required_fields() -> None:
    parser = StrategyParser()
    payload = [{"generation": 1}]
    with pytest.raises(StrategyParseError):
        parser.parse(str(payload).replace("'", '"'))


def test_parses_four_strategies_and_reassigns_id() -> None:
    parser = StrategyParser()
    payload = [_valid_strategy_dict() for _ in range(4)]
    parsed = parser.parse(__import__("json").dumps(payload))
    assert len(parsed) == 4
    assert all(strategy.strategy_id != "old-id" for strategy in parsed)
    assert all(strategy.status == StrategyStatus.SHADOW for strategy in parsed)

