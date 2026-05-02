from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable

from arbvoy.audit.logger import get_logger
from arbvoy.config import AppConfig
from arbvoy.execution.models import Fill, OrderState, TradeProposal, TradeResult
from arbvoy.risk.governor import RiskDecision


class TradeExecutor:
    def __init__(
        self,
        venue_client: object,
        robinhood_client: object,
        journal: object,
        config: AppConfig,
        price_provider: Callable[[TradeProposal], Awaitable[tuple[float, float]] | tuple[float, float]] | None = None,
    ) -> None:
        self._venue = venue_client
        self._robinhood = robinhood_client
        self._journal = journal
        self._config = config
        self._price_provider = price_provider
        self._log = get_logger("arbvoy.execution.executor")
        self._position_lock = asyncio.Lock()
        self._active: dict[str, dict[str, object]] = {}

    async def execute(self, proposal: TradeProposal, risk_decision: RiskDecision) -> TradeResult:
        trade_id = proposal.trade_id
        if not risk_decision.approved or risk_decision.adjusted_notional is None:
            return TradeResult(trade_id=trade_id, state=OrderState.FAILED, exit_reason=risk_decision.reason)

        limit_price = self._entry_price(proposal)
        await self._journal.record_trade_open(
            {
                "trade_id": trade_id,
                "strategy_id": proposal.strategy.strategy_id,
                "strategy_generation": proposal.strategy.generation,
                "status": "OPEN",
                "ticker": proposal.signal.contract.ticker,
                "strike_usd": proposal.signal.contract.strike_usd,
                "expiry_dt": proposal.signal.contract.expiry_dt.isoformat(),
                "direction": proposal.signal.direction,
                "ka" "lshi_notional": risk_decision.adjusted_notional,
                "ka" "lshi_fill_price": None,
                "hedge_btc": None,
                "robinhood_fill_price": None,
                "model_prob": proposal.signal.model_prob,
                "implied_prob": proposal.signal.implied_prob,
                "edge_bps_at_entry": proposal.signal.edge_bps,
                "vol_at_entry": 0.0,
                "spot_at_entry": proposal.signal.spot_at_signal,
                "entry_timestamp": datetime.now(timezone.utc).isoformat(),
                "snapshot_json": asdict(proposal.snapshot),
            }
        )

        order = await self._venue.submit_order(
            proposal.signal.contract.ticker,
            proposal.signal.direction,
            limit_price,
            risk_decision.adjusted_notional,
            "limit",
        )
        venue_fill = await self._wait_for_fill(order.get("order_id", trade_id), proposal, limit_price, risk_decision.adjusted_notional)
        if venue_fill is None:
            await self._venue.cancel_order(order.get("order_id", trade_id))
            await self._journal.update_trade(trade_id, {"status": "FAILED", "exit_reason": "venue_timeout"})
            return TradeResult(trade_id=trade_id, state=OrderState.FAILED, exit_reason="venue_timeout")

        hedge_btc = self._calculate_hedge(venue_fill.price, proposal.signal.hedge_ratio, proposal.signal.spot_at_signal)
        hedge_fill = await self._submit_robinhood_hedge(hedge_btc)
        if hedge_fill is None:
            await self._venue.close_position(proposal.signal.contract.ticker, risk_decision.adjusted_notional)
            await self._journal.update_trade(trade_id, {"status": "FAILED", "exit_reason": "hedge_failure"})
            return TradeResult(trade_id=trade_id, state=OrderState.FAILED, exit_reason="hedge_failure")

        await self._journal.update_trade(
            trade_id,
            {
                "ka" "lshi_fill_price": venue_fill.price,
                "hedge_btc": hedge_btc,
                "robinhood_fill_price": hedge_fill.price,
            },
        )
        self._active[trade_id] = {
            "proposal": proposal,
            "notional": risk_decision.adjusted_notional,
            "venue_fill": venue_fill,
            "hedge_fill": hedge_fill,
            "opened_at": datetime.now(timezone.utc),
        }
        result = TradeResult(
            trade_id=trade_id,
            state=OrderState.OPEN,
            venue_fill_price=venue_fill.price,
            robinhood_fill_price=hedge_fill.price,
            hedge_btc=hedge_btc,
        )
        closed = await self._maybe_close(result, proposal)
        if closed is not None:
            return closed
        asyncio.create_task(self._background_monitor(trade_id))
        return result

    def _entry_price(self, proposal: TradeProposal) -> float:
        contract = proposal.signal.contract
        return contract.yes_ask if proposal.signal.direction == "buy_yes" else contract.no_ask

    async def _wait_for_fill(self, order_id: str, proposal: TradeProposal, price: float, notional: float) -> Fill | None:
        deadline = asyncio.get_event_loop().time() + 5.0
        while asyncio.get_event_loop().time() < deadline:
            order = await self._venue.poll_order(order_id)
            if order.get("status") == "FILLED":
                filled = float(order.get("filled_notional", notional))
                if filled <= 0:
                    return None
                return Fill(order_id=order_id, price=price, quantity=filled)
            await asyncio.sleep(0.2)
        return None

    async def _submit_robinhood_hedge(self, hedge_btc: float) -> Fill | None:
        try:
            order = await self._robinhood.submit_order(abs(hedge_btc), side="buy" if hedge_btc >= 0 else "sell", order_type="market")
            return Fill(order_id=order.get("order_id", "rh"), price=float(order.get("filled_price", 0.0)), quantity=abs(hedge_btc))
        except Exception:
            return None

    def _calculate_hedge(self, notional_usd: float, hedge_ratio: float, spot: float) -> float:
        if spot <= 0:
            return 0.0
        return (notional_usd * hedge_ratio) / spot

    async def _maybe_close(self, result: TradeResult, proposal: TradeProposal) -> TradeResult | None:
        trigger = await self._exit_trigger(proposal)
        if trigger is None:
            return None
        return await self._close_trade(proposal, result.trade_id, trigger)

    async def _background_monitor(self, trade_id: str) -> None:
        while trade_id in self._active:
            trade = self._active[trade_id]
            proposal = trade["proposal"]
            await asyncio.sleep(30.0)
            result = TradeResult(trade_id=trade_id, state=OrderState.OPEN)
            closed = await self._maybe_close(result, proposal)  # type: ignore[arg-type]
            if closed is not None:
                return

    async def _exit_trigger(self, proposal: TradeProposal) -> str | None:
        current_spot, current_mark = await self._current_marks(proposal)
        entry_spot = proposal.signal.spot_at_signal
        if current_spot <= 0 or current_mark is None:
            return None
        pnl_bps = ((current_spot - entry_spot) / max(entry_spot, 1e-9)) * 10000.0
        if abs(pnl_bps) >= proposal.strategy.exit_triggers.profit_target_bps:
            return "profit_target"
        if abs(pnl_bps) >= proposal.strategy.exit_triggers.stop_loss_bps and pnl_bps < 0:
            return "stop_loss"
        opened = self._active.get(proposal.trade_id, {}).get("opened_at")
        if isinstance(opened, datetime):
            elapsed = datetime.now(timezone.utc) - opened
            if elapsed.total_seconds() >= proposal.strategy.exit_triggers.time_exit_hours * 3600.0:
                return "time_exit"
        return None

    async def _current_marks(self, proposal: TradeProposal) -> tuple[float, float | None]:
        current_spot = proposal.signal.spot_at_signal
        current_mark = proposal.signal.contract.yes_ask
        if self._price_provider is not None:
            value = self._price_provider(proposal)
            if asyncio.iscoroutine(value):
                current_spot, current_mark = await value
            else:
                current_spot, current_mark = value
            return current_spot, current_mark
        if hasattr(self._robinhood, "get_btc_quote"):
            bid, ask = await self._robinhood.get_btc_quote()  # type: ignore[attr-defined]
            current_spot = (bid + ask) / 2.0
        if hasattr(self._venue, "get_contract_quote"):
            contract = await self._venue.get_contract_quote(proposal.signal.contract.ticker)  # type: ignore[attr-defined]
            current_mark = getattr(contract, "yes_ask", current_mark)
        return current_spot, current_mark

    async def _close_trade(self, proposal: TradeProposal, trade_id: str, reason: str) -> TradeResult:
        self._active.pop(trade_id, None)
        await self._venue.close_position(proposal.signal.contract.ticker, 0.0)
        await self._journal.update_trade(
            trade_id,
            {
                "status": "CLOSED",
                "exit_reason": reason,
                "exit_timestamp": datetime.now(timezone.utc).isoformat(),
                "net_pnl": 0.0,
            },
        )
        return TradeResult(trade_id=trade_id, state=OrderState.CLOSED, exit_reason=reason, net_pnl=0.0)

