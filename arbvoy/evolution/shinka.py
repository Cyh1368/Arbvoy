from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Callable

from arbvoy.audit.logger import get_logger, log_event
from arbvoy.config import AppConfig
from arbvoy.evolution.fitness import FitnessEvaluator
from arbvoy.evolution.prompt_builder import PromptBuilder
from arbvoy.evolution.shadow_tester import ShadowTester
from arbvoy.evolution.strategy_parser import StrategyParser
from arbvoy.exceptions import StrategyParseError
from arbvoy.strategy.models import EntryConditions, ExitTriggers, RegimeTag, SizingRules, Strategy, StrategyStatus

try:
    import anthropic  # type: ignore
except Exception:  # pragma: no cover
    anthropic = None  # type: ignore[assignment]


@dataclass(slots=True)
class ShinkaEvolution:
    config: AppConfig
    db: object
    strategy_registry: object
    prompt_builder: PromptBuilder = field(default_factory=PromptBuilder)
    parser: StrategyParser = field(default_factory=StrategyParser)
    fitness_evaluator: FitnessEvaluator = field(default_factory=FitnessEvaluator)
    shadow_tester_factory: Callable[[], ShadowTester] | None = None
    client_factory: Callable[[], object] | None = None
    _log: object = field(default_factory=lambda: get_logger("arbvoy.evolution.shinka"))

    async def run_cycle(self) -> dict[str, int]:
        log_event(get_logger("arbvoy.evolution.shinka"), 20, "EVOLVE", "[EVOLVE] Starting evolution cycle")
        strategies = self.strategy_registry.live()
        promoted = 0
        archived = 0
        shadow = 0
        scored: list[Strategy] = []
        for strategy in strategies:
            score = await self.fitness_evaluator.evaluate(strategy.strategy_id, self.db)
            if score is not None:
                strategy = strategy.model_copy(update={"fitness": score})
                await self.strategy_registry.upsert(strategy)
                scored.append(strategy)
        scored = sorted(scored, key=lambda s: s.fitness.composite if s.fitness else -1.0, reverse=True)
        condemned = [s for s in scored[-2:] if (s.fitness and s.fitness.trade_count >= 20)]
        prompt = await self.prompt_builder.build(self.db, self.strategy_registry)
        new_strategies: list[Strategy] = []
        last_error = ""
        for _ in range(3):
            response_text = await self._generate_strategies(prompt, last_error)
            try:
                new_strategies = self.parser.parse(response_text)
                break
            except StrategyParseError as exc:
                last_error = str(exc)
        if not new_strategies:
            await self.db.record_audit_event("ERROR", {"event": "strategy_parse_failed", "error": last_error})
            return {"promoted": promoted, "archived": archived, "shadow": shadow}
        for strategy in new_strategies:
            await self.strategy_registry.upsert(strategy)
            shadow += 1
            if self.shadow_tester_factory is not None:
                tester = self.shadow_tester_factory()
                asyncio.create_task(tester.run_shadow_cycle(strategy, asyncio.Queue()))
        for candidate, doomed in zip(new_strategies, condemned):
            if candidate.fitness is not None and doomed.fitness is not None and candidate.fitness.composite > doomed.fitness.composite:
                await self.strategy_registry.promote(candidate.strategy_id)
                await self.strategy_registry.archive(doomed.strategy_id)
                promoted += 1
                archived += 1
        await self.db.record_audit_event(
            "EVOLVE",
            {
                "promoted": promoted,
                "archived": archived,
                "shadow": shadow,
                "cycle": "complete",
            },
        )
        return {"promoted": promoted, "archived": archived, "shadow": shadow}

    async def _generate_strategies(self, prompt: object, correction: str = "") -> str:
        client_factory = self.client_factory
        if client_factory is None:
            if anthropic is None:
                return self._fallback_response()
            client = anthropic.AsyncAnthropic(api_key=self.config.ANTHROPIC_API_KEY)
        else:
            client = client_factory()
        system = getattr(prompt, "system", "")
        user = getattr(prompt, "user", str(prompt))
        try:
            response = await client.messages.create(  # type: ignore[attr-defined]
                model="claude-sonnet-4-5",
                max_tokens=2000,
                system=system,
                messages=[{"role": "user", "content": user + (f"\n\nCorrection request: {correction}" if correction else "")}],
            )
            content = response.content[0].text if getattr(response, "content", None) else ""
            return content
        except Exception as exc:
            if anthropic is not None and isinstance(exc, getattr(anthropic, "APIError", Exception)):
                return self._fallback_response()
            return self._fallback_response()

    @staticmethod
    def _fallback_response() -> str:
        payload = [
            Strategy(
                strategy_id="",
                parent_id=None,
                generation=1,
                status=StrategyStatus.SHADOW,
                regime_tags=[RegimeTag.ANY],
                entry_conditions=EntryConditions(),
                sizing_rules=SizingRules(),
                exit_triggers=ExitTriggers(),
                mutation_rationale="Fallback generated strategy",
            ).model_dump(mode="json")
            for _ in range(4)
        ]
        return json.dumps(payload)


def _build_default_orchestrator(config: AppConfig, db: object, registry: object) -> ShinkaEvolution:
    return ShinkaEvolution(config=config, db=db, strategy_registry=registry)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-cycle", action="store_true")
    args = parser.parse_args()
    if args.force_cycle:
        from arbvoy.config import load_config
        from arbvoy.journal.db import JournalDB
        from arbvoy.strategy.registry import StrategyRegistry

        config = load_config()
        db = JournalDB(config.DB_PATH)
        await db.initialize()
        registry = StrategyRegistry(db)
        await registry.refresh()
        orchestrator = ShinkaEvolution(config=config, db=db, strategy_registry=registry)
        await orchestrator.run_cycle()


if __name__ == "__main__":
    asyncio.run(main())
