from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

from arbvoy.exceptions import StrategyParseError
from arbvoy.strategy.models import Strategy, StrategyStatus


class StrategyParser:
    def parse(self, claude_response_text: str) -> list[Strategy]:
        text = claude_response_text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise StrategyParseError(f"invalid json: {exc}") from exc
        if not isinstance(payload, list) or len(payload) != 4:
            raise StrategyParseError("response must be a list of exactly 4 items")
        strategies: list[Strategy] = []
        base_created_at = datetime.now(timezone.utc)
        for index, item in enumerate(payload):
            try:
                strategy = Strategy.model_validate(item)
            except Exception as exc:
                raise StrategyParseError(f"schema mismatch: {exc}") from exc
            created_at = base_created_at + timedelta(microseconds=index)
            strategy = strategy.model_copy(
                update={
                    "strategy_id": self._strategy_id(created_at, strategy.parent_id),
                    "status": StrategyStatus.SHADOW,
                    "created_at": created_at,
                }
            )
            strategies.append(strategy)
        return strategies

    @staticmethod
    def _strategy_id(created_at: datetime, parent_id: str | None) -> str:
        seed = f"{created_at.isoformat()}:{parent_id or ''}".encode("utf-8")
        return hashlib.sha256(seed).hexdigest()[:12]
