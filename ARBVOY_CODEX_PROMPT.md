# ARBVOY — CODEX INITIAL BUILD PROMPT
# Probability Mispricing Arbitrage: Kalshi × Robinhood BTC

> Paste this entire file as your first message to Codex.
> Codex should scaffold, implement, test, and wire up every component described below.
> Do not ask for clarification — make reasonable implementation decisions and document them inline.

---

## MISSION

Build **ArbitrageVoy** — an autonomous, closed-loop Python trading system that exploits
probability mispricing between Kalshi BTC prediction market contracts and Robinhood BTC
spot price. The system runs continuously without human intervention, self-improves its
trading logic via scheduled Claude AI-driven strategy evolution (ShinkaEvolve), and emits
a structured live audit log stream that humans can monitor.

The strategy is **probability mispricing arbitrage only**:
- Derive a model probability that BTC will be above a given strike at contract expiry,
  using the current spot price and realized volatility.
- Compare model probability to Kalshi's implied probability (the YES contract price).
- When divergence exceeds a configurable threshold, trade the mispriced side on Kalshi
  and delta-hedge the directional BTC exposure on Robinhood.

---

## TECH STACK

| Layer          | Choice                   | Rationale                                      |
|----------------|--------------------------|------------------------------------------------|
| Language        | Python 3.11+             | Ecosystem, async support, quant libs           |
| Async runtime   | asyncio + aiohttp        | Non-blocking WebSocket + REST                  |
| Scheduling      | APScheduler              | Evolution cycles, periodic vol recalc          |
| Database        | SQLite via aiosqlite     | Zero-ops, sufficient for single-bot scale      |
| AI evolution    | Anthropic Python SDK     | claude-sonnet-4-5 for strategy generation      |
| Logging         | Python structlog         | JSON + human-readable dual output              |
| Config          | Pydantic v2 + .env       | Validated settings, no magic strings           |
| Testing         | pytest + pytest-asyncio  | Full unit + integration test suite             |
| Linting         | ruff + mypy              | Enforced on every module                       |

---

## PROJECT STRUCTURE

Scaffold this exact directory layout. Every `__init__.py` must be present.

```
arbvoy/
├── README.md
├── pyproject.toml                  # all deps, ruff + mypy config
├── .env.example                    # template — never commit real secrets
├── run.py                          # entrypoint: `python run.py`
│
├── arbvoy/
│   ├── __init__.py
│   ├── config.py                   # Pydantic Settings — all env vars
│   │
│   ├── feeds/
│   │   ├── __init__.py
│   │   ├── kalshi_feed.py          # Kalshi WebSocket feed
│   │   ├── robinhood_feed.py       # Robinhood REST polling
│   │   └── models.py               # MarketSnapshot, ContractQuote dataclasses
│   │
│   ├── signals/
│   │   ├── __init__.py
│   │   ├── probability_model.py    # Lognormal model probability (Black-Scholes style)
│   │   ├── vol_estimator.py        # Realized vol calculation from price ring buffer
│   │   ├── signal_engine.py        # Produces OpportunitySet from MarketSnapshot
│   │   └── models.py               # OpportunitySet, PricingSignal dataclasses
│   │
│   ├── strategy/
│   │   ├── __init__.py
│   │   ├── registry.py             # StrategyRegistry — CRUD, fitness ranking
│   │   ├── selector.py             # Regime detection + strategy selection
│   │   ├── models.py               # Strategy, StrategyStatus, RegimeTag enums
│   │   └── defaults.py             # Hardcoded seed strategy (generation 0)
│   │
│   ├── risk/
│   │   ├── __init__.py
│   │   └── governor.py             # All pre-trade risk checks
│   │
│   ├── execution/
│   │   ├── __init__.py
│   │   ├── kalshi_client.py        # Kalshi REST order submission
│   │   ├── robinhood_client.py     # Robinhood crypto order submission
│   │   ├── executor.py             # Dual-leg coordinator state machine
│   │   └── models.py               # TradeProposal, OrderState, Fill dataclasses
│   │
│   ├── journal/
│   │   ├── __init__.py
│   │   ├── db.py                   # SQLite schema + aiosqlite connection pool
│   │   └── writer.py               # Atomic journal writes
│   │
│   ├── evolution/
│   │   ├── __init__.py
│   │   ├── fitness.py              # Fitness scoring: Sharpe, win rate, avg PnL
│   │   ├── shinka.py               # Main evolution cycle orchestrator
│   │   ├── prompt_builder.py       # Builds Claude prompt from journal data
│   │   ├── strategy_parser.py      # Validates + parses Claude JSON response
│   │   └── shadow_tester.py        # Paper-trades new strategies before promotion
│   │
│   ├── audit/
│   │   ├── __init__.py
│   │   └── logger.py               # structlog setup: JSON file + human console
│   │
│   └── orchestrator.py             # Main loop — wires all layers together
│
└── tests/
    ├── conftest.py
    ├── test_probability_model.py
    ├── test_signal_engine.py
    ├── test_risk_governor.py
    ├── test_fitness.py
    ├── test_strategy_parser.py
    ├── test_executor.py            # Uses mocked exchange clients
    └── test_evolution_cycle.py     # End-to-end evolution with mocked Claude
```

---

## MODULE SPECIFICATIONS

Implement each module to exactly these specifications. Use type hints on every function.
Raise typed exceptions — never bare `Exception`. Log every significant action via `audit.logger`.

---

### `config.py`

```python
# All settings via Pydantic BaseSettings. Source from environment / .env file.
# Required fields (no defaults — fail loudly if missing):
#   KALSHI_API_KEY: str
#   KALSHI_API_SECRET: str          # used for HMAC request signing
#   ROBINHOOD_API_KEY: str
#   ROBINHOOD_ACCOUNT_NUMBER: str
#   ANTHROPIC_API_KEY: str
#
# Fields with defaults:
#   KALSHI_BASE_URL: str = "https://trading-api.kalshi.com/trade-api/v2"
#   KALSHI_WS_URL: str = "wss://trading-api.kalshi.com/trade-api/ws/v2"
#   ROBINHOOD_BASE_URL: str = "https://trading.robinhood.com"
#   SNAPSHOT_INTERVAL_SECONDS: float = 1.0
#   RING_BUFFER_SIZE: int = 3600         # 1 hour at 1s intervals
#   MIN_EDGE_BPS: int = 300              # 3% minimum edge to enter
#   MAX_KALSHI_NOTIONAL_PER_CONTRACT: float = 500.0
#   MAX_TOTAL_KALSHI_NOTIONAL: float = 2000.0
#   MAX_ROBINHOOD_HEDGE_NOTIONAL: float = 1000.0
#   DAILY_LOSS_LIMIT_PCT: float = 0.03   # halt if daily PnL < -3%
#   STOP_LOSS_BPS: int = 150
#   PROFIT_TARGET_BPS: int = 300
#   TIME_EXIT_HOURS: float = 24.0
#   KELLY_FRACTION: float = 0.25
#   EVOLUTION_TRADE_INTERVAL: int = 50   # evolve every N live trades
#   SHADOW_TRADE_COUNT: int = 20
#   STRATEGY_POPULATION_SIZE: int = 10
#   LOG_FILE_PATH: str = "logs/arbvoy.jsonl"
#   DB_PATH: str = "data/arbvoy.db"
```

---

### `feeds/models.py`

```python
# ContractQuote: ticker, strike_usd, expiry_dt, yes_ask, no_ask, yes_bid, no_bid,
#                volume_24h, open_interest
#                property: implied_probability -> float = yes_ask (Kalshi 0-1 scale)
#                property: spread_arb_score -> float = 1.0 - (yes_ask + no_ask)
#
# MarketSnapshot: timestamp, btc_spot_mid, btc_spot_bid, btc_spot_ask,
#                 contracts: list[ContractQuote]
```

---

### `feeds/kalshi_feed.py`

```python
# KalshiFeed class
# - Connects to Kalshi WebSocket using aiohttp ClientSession
# - Authenticates via HMAC-SHA256 signed headers on each REST call
# - On connect: subscribes to orderbook_delta channel for all active
#   BTC-price series (series slug: "KXBTC" or equivalent)
# - Maintains in-memory dict of current best bid/ask per contract ticker
# - Exposes: async def get_contracts() -> list[ContractQuote]
# - Reconnects automatically with exponential backoff (max 60s) on disconnect
# - Kalshi REST auth: sign the path + timestamp + body with HMAC-SHA256,
#   add headers: KALSHI-ACCESS-KEY, KALSHI-ACCESS-TIMESTAMP, KALSHI-ACCESS-SIGNATURE
# - On startup: fetch all active BTC markets via REST GET /markets?series_ticker=KXBTC
#   to seed the initial contract list before WebSocket streaming begins
```

---

### `feeds/robinhood_feed.py`

```python
# RobinhoodFeed class
# - Polls Robinhood crypto GET /api/v1/crypto/trading/best_bid_ask/?symbol=BTC-USD
#   every SNAPSHOT_INTERVAL_SECONDS seconds
# - Auth: Bearer token via Robinhood API key (Ed25519 signed requests)
# - Exposes: async def get_btc_quote() -> tuple[float, float]  # (bid, ask)
# - Implements token bucket rate limiting: max 10 requests/second
# - Robinhood crypto API auth pattern:
#     private_key = Ed25519PrivateKey loaded from ROBINHOOD_API_KEY (base64 PEM)
#     message = f"{api_key}{timestamp}{path}{body}"
#     signature = base64(private_key.sign(message.encode()))
#     headers: x-api-key, x-timestamp, x-signature
```

---

### `signals/probability_model.py`

```python
# ProbabilityModel class
#
# method: model_probability(spot: float, strike: float, days_to_expiry: float,
#                            annualized_vol: float) -> float
#   Uses lognormal (Black-Scholes) framework:
#     T = days_to_expiry / 365
#     d2 = (ln(spot/strike) + (-0.5 * vol^2) * T) / (vol * sqrt(T))
#     probability = N(d2)     # scipy.stats.norm.cdf(d2)
#   Returns probability that BTC > strike at expiry.
#   Edge cases: if T <= 0, return 1.0 if spot > strike else 0.0
#
# method: hedge_ratio(spot: float, strike: float, days_to_expiry: float,
#                      annualized_vol: float) -> float
#   Returns BTC units to buy/sell per $1 of Kalshi YES contract notional
#   to achieve delta-neutral combined position.
#   Approximate: dP/dS ≈ N'(d2) / (spot * vol * sqrt(T))
#   where N'() is the standard normal PDF.
#   NOTE: sign convention — positive = long BTC hedge (used when buying NO on Kalshi)
```

---

### `signals/vol_estimator.py`

```python
# VolEstimator class
# - Maintains a ring buffer (collections.deque, maxlen=RING_BUFFER_SIZE) of BTC mid prices
# - method: update(price: float) -> None   — called every snapshot
# - method: annualized_vol() -> float
#     Compute log returns from ring buffer prices.
#     Use exponentially weighted variance: lambda=0.94 (RiskMetrics standard)
#     Annualize: vol_annual = vol_1s * sqrt(365 * 24 * 3600)
#     Minimum vol floor: 0.30 (30% annualized) — BTC never truly calm
#     Maximum vol cap: 2.50 (250% annualized) — circuit breaker
# - method: has_sufficient_data() -> bool
#     Returns True only if buffer has >= 300 data points (5 minutes at 1s intervals)
#     System will NOT trade until this returns True on startup
```

---

### `signals/signal_engine.py`

```python
# SignalEngine class
# Takes MarketSnapshot + VolEstimator → produces OpportunitySet
#
# For each ContractQuote in snapshot:
#   1. Skip if days_to_expiry <= 0 or volume_24h < MIN_KALSHI_VOLUME_24H (config, default 1000)
#   2. model_prob = probability_model.model_probability(spot, strike, dte, vol)
#   3. implied_prob = contract.implied_probability
#   4. edge_bps = abs(implied_prob - model_prob) * 10000
#   5. direction = "buy_no" if implied_prob > model_prob else "buy_yes"
#      (if market overestimates probability, buy NO = bet against it)
#   6. hedge_ratio = probability_model.hedge_ratio(spot, strike, dte, vol)
#      sign flip: if direction == "buy_no", hedge is LONG BTC (positive delta)
#                 if direction == "buy_yes", hedge is SHORT BTC (negative delta)
#   7. Emit PricingSignal if edge_bps >= MIN_EDGE_BPS
#
# OpportunitySet: list[PricingSignal], snapshot_timestamp, spot_price, vol_used
# PricingSignal: contract, model_prob, implied_prob, edge_bps, direction,
#                hedge_ratio, spot_at_signal
```

---

### `strategy/models.py`

```python
# Strategy dataclass (also serializes to/from JSON for Claude I/O):
#   strategy_id: str              # sha256[:12] of creation timestamp + parent_id
#   parent_id: str | None
#   generation: int
#   status: StrategyStatus        # SHADOW | LIVE | ARCHIVED
#   regime_tags: list[RegimeTag]  # HIGH_VOL | LOW_VOL | TRENDING | RANGING | ANY
#   entry_conditions: EntryConditions
#   sizing_rules: SizingRules
#   exit_triggers: ExitTriggers
#   fitness: FitnessScore | None  # None until evaluated
#   mutation_rationale: str       # Claude's explanation
#   created_at: datetime
#
# EntryConditions:
#   min_edge_bps: int             # minimum signal edge (default 300)
#   min_days_to_expiry: float     # (default 0.5)
#   max_days_to_expiry: float     # (default 7.0)
#   min_volume_24h: float         # (default 1000)
#   direction_filter: str         # "any" | "buy_yes" | "buy_no"
#
# SizingRules:
#   base_notional_usd: float      # (default 200)
#   kelly_fraction: float         # (default 0.25)
#   max_notional_usd: float       # hard cap (default 500)
#
# ExitTriggers:
#   profit_target_bps: int        # (default 300)
#   stop_loss_bps: int            # (default 150)
#   time_exit_hours: float        # (default 24)
#
# FitnessScore:
#   sharpe: float
#   win_rate: float
#   avg_pnl_bps: float
#   trade_count: int
#   composite: float              # 0.4*sharpe + 0.3*win_rate + 0.2*norm(avg_pnl) + 0.1*norm(trade_count)
```

---

### `strategy/defaults.py`

```python
# Defines SEED_STRATEGY: the generation-0 strategy that the bot starts with.
# This is the conservative baseline — it is hardcoded and never replaced,
# only archived if it falls below fitness threshold after sufficient data.
# Use default values from strategy/models.py EntryConditions, SizingRules, ExitTriggers.
# regime_tags = [RegimeTag.ANY]
# mutation_rationale = "Seed strategy — human authored"
# generation = 0, parent_id = None
```

---

### `risk/governor.py`

```python
# RiskGovernor class
# Initialized with: config, journal reference (to query daily PnL, open positions)
#
# method: async def check(proposal: TradeProposal) -> RiskDecision
#   Runs ALL checks in sequence. First failure blocks and returns reason.
#   Checks (in order):
#     1. DAILY_LOSS_HALT: if today's realized PnL < -(capital * DAILY_LOSS_LIMIT_PCT) → BLOCK
#     2. POSITION_LIMIT: if total open Kalshi notional >= MAX_TOTAL_KALSHI_NOTIONAL → BLOCK
#     3. CONTRACT_LIMIT: if open notional for this specific ticker >= MAX_KALSHI_NOTIONAL_PER_CONTRACT → BLOCK
#     4. HEDGE_LIMIT: if proposed Robinhood hedge would exceed MAX_ROBINHOOD_HEDGE_NOTIONAL → SCALE DOWN (not block)
#     5. CIRCUIT_BREAKER: if 15-min BTC price move >= 5% → BLOCK (stored in ring buffer)
#     6. MIN_LIQUIDITY: if contract.volume_24h < proposal.strategy.entry_conditions.min_volume_24h → BLOCK
#     7. DUPLICATE: if identical (ticker, direction) position already open → BLOCK
#   All checks PASS → APPROVED with final sized notional
#
# RiskDecision: approved: bool, reason: str | None, adjusted_notional: float | None
```

---

### `execution/executor.py`

```python
# TradeExecutor class — dual-leg state machine
#
# States: IDLE → LEG1_PENDING → LEG1_FILLED → LEG2_PENDING → OPEN → CLOSING → CLOSED | FAILED
#
# method: async def execute(proposal: TradeProposal, risk_decision: RiskDecision) -> TradeResult
#   Step 1: Submit Kalshi limit order at signal price ± SLIPPAGE_TOLERANCE_BPS (default 10bps)
#           Wait up to 5 seconds for fill confirmation via polling.
#           If timeout or partial fill: cancel, move to FAILED. No Robinhood order placed.
#   Step 2: On Kalshi fill, compute hedge_btc = filled_notional * signal.hedge_ratio / btc_spot
#           Submit Robinhood market order for hedge_btc BTC.
#           If Robinhood fails: emergency close Kalshi position immediately.
#   Step 3: State = OPEN. Record all fill data to journal.
#   Step 4: Start async exit monitor (checks profit target, stop loss, time exit every 30s).
#   Step 5: On exit trigger: close Kalshi position first, then unwind Robinhood hedge.
#           Compute final PnL = kalshi_pnl + robinhood_pnl - estimated_fees.
#           Write closed trade to journal. Increment trade counter.
#
# IMPORTANT: All Kalshi orders are LIMIT orders. Robinhood hedge is MARKET order.
# IMPORTANT: Executor is reentrant — multiple positions can be open simultaneously
#            up to risk limits. Use asyncio.Lock only for position count checks.
```

---

### `journal/db.py`

```python
# Database schema — create on startup if not exists:
#
# TABLE trades:
#   id INTEGER PRIMARY KEY AUTOINCREMENT
#   trade_id TEXT UNIQUE NOT NULL           -- uuid4
#   strategy_id TEXT NOT NULL
#   strategy_generation INTEGER NOT NULL
#   status TEXT NOT NULL                    -- OPEN | CLOSED | FAILED
#   ticker TEXT NOT NULL
#   strike_usd REAL NOT NULL
#   expiry_dt TEXT NOT NULL
#   direction TEXT NOT NULL                 -- buy_yes | buy_no
#   kalshi_notional REAL NOT NULL
#   kalshi_fill_price REAL
#   hedge_btc REAL
#   robinhood_fill_price REAL
#   model_prob REAL NOT NULL
#   implied_prob REAL NOT NULL
#   edge_bps_at_entry REAL NOT NULL
#   vol_at_entry REAL NOT NULL
#   spot_at_entry REAL NOT NULL
#   entry_timestamp TEXT NOT NULL
#   exit_timestamp TEXT
#   exit_reason TEXT                        -- profit_target | stop_loss | time_exit | emergency
#   kalshi_pnl REAL
#   robinhood_pnl REAL
#   fees_usd REAL
#   net_pnl REAL
#   slippage_bps REAL
#   snapshot_json TEXT                      -- full MarketSnapshot at entry as JSON
#
# TABLE strategies:
#   id INTEGER PRIMARY KEY AUTOINCREMENT
#   strategy_id TEXT UNIQUE NOT NULL
#   parent_id TEXT
#   generation INTEGER NOT NULL
#   status TEXT NOT NULL                    -- SHADOW | LIVE | ARCHIVED
#   strategy_json TEXT NOT NULL             -- full Strategy object as JSON
#   fitness_json TEXT                       -- FitnessScore as JSON, null until evaluated
#   promoted_at TEXT
#   archived_at TEXT
#   created_at TEXT NOT NULL
#
# TABLE audit_events:
#   id INTEGER PRIMARY KEY AUTOINCREMENT
#   event_type TEXT NOT NULL               -- SIGNAL | RISK_BLOCK | ORDER | FILL | EXIT | EVOLVE | ERROR
#   payload_json TEXT NOT NULL
#   timestamp TEXT NOT NULL
```

---

### `evolution/fitness.py`

```python
# FitnessEvaluator class
#
# method: async def evaluate(strategy_id: str, db) -> FitnessScore
#   Queries trades table for all CLOSED trades with this strategy_id.
#   Requires >= 10 trades to compute meaningful score (return None if fewer).
#   Compute:
#     returns = [trade.net_pnl / trade.kalshi_notional for each trade]
#     sharpe = mean(returns) / std(returns) * sqrt(252)   # annualized, 0 if std=0
#     win_rate = count(net_pnl > 0) / total_trades
#     avg_pnl_bps = mean(returns) * 10000
#     composite = 0.4 * clamp(sharpe/3, 0, 1)
#                 + 0.3 * win_rate
#                 + 0.2 * clamp(avg_pnl_bps/500, 0, 1)
#                 + 0.1 * clamp(trade_count/100, 0, 1)
```

---

### `evolution/prompt_builder.py`

```python
# PromptBuilder class
#
# method: async def build(db, strategy_registry) -> str
#   Queries journal for:
#     - Last 200 closed trades (recent performance context)
#     - Per-strategy fitness summary
#     - The 2 worst-performing LIVE strategies (full Strategy JSON = mutation targets)
#     - The 3 best-performing LIVE strategies (full Strategy JSON = reference)
#     - Recent market regime stats (avg vol, avg edge_bps seen, trade frequency)
#   Formats as structured JSON payload wrapped in a system + user prompt.
#
# SYSTEM PROMPT (exact text — do not modify):
# """
# You are a quantitative trading strategy optimizer for a Bitcoin prediction market
# arbitrage system. You identify why trading strategies underperform and generate
# improved variants. You must respond with ONLY a valid JSON array of exactly 4
# Strategy objects matching the schema provided. No prose, no markdown, no explanation
# outside the JSON. Each object must include a mutation_rationale field explaining
# your reasoning in 1-2 sentences.
# """
#
# USER PROMPT structure:
# {
#   "task": "Generate 4 improved strategies: 3 mutations of the worst performers, 1 novel.",
#   "strategy_schema": <StrategyObject JSON schema>,
#   "regime_context": { "avg_vol_30d": float, "avg_edge_bps": float, "trade_freq_per_day": float },
#   "worst_strategies": [ <Strategy JSON>, <Strategy JSON> ],
#   "elite_strategies": [ <Strategy JSON>, <Strategy JSON>, <Strategy JSON> ],
#   "recent_trade_summary": { "total_trades": int, "win_rate": float, "avg_pnl_bps": float,
#                             "worst_exit_reasons": [...] }
# }
```

---

### `evolution/strategy_parser.py`

```python
# StrategyParser class
#
# method: parse(claude_response_text: str) -> list[Strategy]
#   1. Strip any accidental markdown fences (```json ... ```)
#   2. json.loads() the text — raise StrategyParseError on failure
#   3. Validate it is a list of exactly 4 items
#   4. For each item, validate all required fields exist and are correct types
#      using Pydantic model_validate(). Raise StrategyParseError on schema mismatch.
#   5. Assign new strategy_id (sha256 hash), status=SHADOW, created_at=now()
#   6. Return list[Strategy]
#
# On StrategyParseError: caller (shinka.py) retries up to 3 times with
# the error message appended to the prompt as a correction request.
# After 3 failures: log ERROR, skip evolution cycle, do not modify registry.
```

---

### `evolution/shadow_tester.py`

```python
# ShadowTester class
#
# Simulates strategy entry/exit on LIVE market data without placing real orders.
# Runs alongside the live trading loop as a background asyncio task.
#
# method: async def run_shadow_cycle(strategy: Strategy, signal_queue: asyncio.Queue)
#   Listens to a copy of the live OpportunitySet stream.
#   For each signal that meets strategy.entry_conditions:
#     - Simulate entry at current ask price (no slippage model — conservative)
#     - Track simulated position: entry price, entry time, strategy exit triggers
#     - Simulate exit at profit target / stop loss / time exit using subsequent snapshots
#     - Record simulated trade to trades table with status=SHADOW
#   After SHADOW_TRADE_COUNT simulated trades: trigger fitness evaluation.
#   If shadow fitness > lowest live strategy fitness: emit PROMOTION_CANDIDATE event.
#   ShadowTester does not promote automatically — shinka.py handles promotion logic.
```

---

### `evolution/shinka.py`

```python
# ShinkaEvolution class — the main evolution orchestrator
# Triggered by APScheduler: every EVOLUTION_TRADE_INTERVAL live trades
#
# method: async def run_cycle()
#   1. LOG "[EVOLVE] Starting evolution cycle"
#   2. Evaluate fitness for all LIVE strategies with >= 10 trades
#   3. Rank strategies by composite fitness
#   4. Identify condemned strategies (bottom 2 by fitness, only if trade_count >= 20)
#   5. Build prompt via PromptBuilder
#   6. Call Anthropic API:
#        client = anthropic.AsyncAnthropic()
#        response = await client.messages.create(
#            model="claude-sonnet-4-5",
#            max_tokens=2000,
#            system=prompt.system,
#            messages=[{"role": "user", "content": prompt.user}]
#        )
#   7. Parse response via StrategyParser (retry up to 3x on failure)
#   8. Insert new strategies into DB with status=SHADOW
#   9. Launch ShadowTester tasks for each new strategy
#   10. Check for promotion candidates from previous shadow cycles:
#       - If shadow_fitness > condemned_strategy_fitness: promote shadow, archive condemned
#       - New strategy enters live pool at 25% of normal base_notional for first 50 live trades
#       - After 50 live trades at reduced size: remove size restriction
#   11. LOG "[EVOLVE] Cycle complete: N promoted, N archived, N in shadow"
#   12. Write full evolution event to audit_events table
```

---

### `orchestrator.py`

```python
# MainOrchestrator — wires everything together and runs the main loop
#
# async def run():
#   1. Load config, initialize all components
#   2. Initialize SQLite DB (create tables if not exist)
#   3. Load strategy registry from DB. If empty: insert SEED_STRATEGY as LIVE.
#   4. Start KalshiFeed WebSocket connection
#   5. Start RobinhoodFeed polling loop
#   6. Wait until VolEstimator.has_sufficient_data() (max 10 minute wait with progress logs)
#   7. Start APScheduler for evolution triggers
#   8. Start shadow tester background tasks for any existing SHADOW strategies
#   9. Main loop (runs forever):
#        snapshot = await build_snapshot(kalshi_feed, robinhood_feed)
#        vol_estimator.update(snapshot.btc_spot_mid)
#        if not vol_estimator.has_sufficient_data(): continue
#
#        opportunity_set = signal_engine.process(snapshot)
#        for signal in opportunity_set.signals:
#            strategy = strategy_selector.select(signal, strategy_registry)
#            if strategy is None: continue
#
#            proposal = TradeProposal(signal=signal, strategy=strategy,
#                                     snapshot=snapshot)
#            risk_decision = await risk_governor.check(proposal)
#
#            if not risk_decision.approved:
#                audit_log.info("RISK_BLOCK", reason=risk_decision.reason, signal=signal)
#                continue
#
#            asyncio.create_task(executor.execute(proposal, risk_decision))
#            # Non-blocking: multiple positions can open concurrently
#
#        await asyncio.sleep(config.SNAPSHOT_INTERVAL_SECONDS)
#
# if __name__ == "__main__": asyncio.run(run())
```

---

### `audit/logger.py`

```python
# Configure structlog with dual output:
#   1. Console: human-readable colored output with timestamp prefix
#      Format: "HH:MM:SS [LEVEL] [MODULE] message key=value key=value"
#   2. File (LOG_FILE_PATH): one JSON object per line (JSONL)
#      Include: timestamp, level, event_type, all key-value context
#
# Log levels and their trigger events:
#   INFO:    Snapshot received, signal detected, position opened/closed, evolution cycle start/end
#   WARNING: Partial fill, risk block, shadow strategy underperforming
#   ERROR:   API connection failure, Claude parse error, emergency hedge unwind
#   DEBUG:   Individual probability calculations, vol updates (off by default)
#
# Every log call should include at minimum: timestamp, module, event_type.
# Trade-related logs include: trade_id, strategy_id, ticker, pnl (if applicable).
```

---

## DEPENDENCY LIST (`pyproject.toml`)

```toml
[project]
name = "arbvoy"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = [
    "aiohttp>=3.9",
    "aiosqlite>=0.20",
    "anthropic>=0.30",
    "apscheduler>=3.10",
    "cryptography>=42.0",      # Ed25519 for Robinhood auth
    "numpy>=1.26",
    "scipy>=1.12",
    "pydantic>=2.6",
    "pydantic-settings>=2.2",
    "structlog>=24.1",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-mock>=3.12",
    "ruff>=0.4",
    "mypy>=1.9",
]
```

---

## `.env.example`

```env
# Kalshi API credentials (from kalshi.com developer portal)
KALSHI_API_KEY=your_kalshi_api_key_here
KALSHI_API_SECRET=your_kalshi_api_secret_here

# Robinhood Crypto API credentials (from robinhood.com/api)
ROBINHOOD_API_KEY=your_robinhood_api_key_here
ROBINHOOD_ACCOUNT_NUMBER=your_robinhood_account_number_here

# Anthropic API (from console.anthropic.com)
ANTHROPIC_API_KEY=sk-ant-...

# Trading parameters (optional — defaults shown)
MIN_EDGE_BPS=300
MAX_KALSHI_NOTIONAL_PER_CONTRACT=500
MAX_TOTAL_KALSHI_NOTIONAL=2000
DAILY_LOSS_LIMIT_PCT=0.03
EVOLUTION_TRADE_INTERVAL=50
SHADOW_TRADE_COUNT=20
LOG_FILE_PATH=logs/arbvoy.jsonl
DB_PATH=data/arbvoy.db
```

---

## TEST SPECIFICATIONS

Every test must pass with `pytest tests/ -v`. No test may hit real APIs.
All exchange clients and Anthropic client must be mockable via dependency injection.

### `test_probability_model.py`
- ATM call (spot == strike, 7 days): model_prob should be ~0.49–0.51
- Deep ITM (spot = 110k, strike = 100k, 1 day, vol=0.8): model_prob > 0.90
- Deep OTM (spot = 90k, strike = 100k, 1 day, vol=0.8): model_prob < 0.10
- At expiry (T=0): returns 1.0 if spot > strike, 0.0 otherwise
- Hedge ratio is always positive and < 1.0 for reasonable inputs

### `test_signal_engine.py`
- Signal emitted when |implied - model| > MIN_EDGE_BPS / 10000
- No signal when volume_24h below threshold
- No signal when contract is expired
- Direction is "buy_no" when implied_prob > model_prob
- Direction is "buy_yes" when implied_prob < model_prob

### `test_risk_governor.py`
- BLOCK when daily loss limit exceeded (mock journal returning large negative PnL)
- BLOCK when position limit at max
- BLOCK when circuit breaker active (mock 6% 15-min price move)
- APPROVED when all checks pass
- SCALE DOWN hedge when hedge would exceed limit (not a full block)

### `test_fitness.py`
- Returns None when < 10 trades
- Sharpe of 0 when all trades break even
- Composite score between 0.0 and 1.0 for valid inputs
- Higher composite for strategy with better Sharpe AND higher win rate

### `test_strategy_parser.py`
- Raises StrategyParseError on non-JSON response
- Raises StrategyParseError if result is not a list of 4
- Raises StrategyParseError on missing required fields
- Successfully parses valid JSON list of 4 Strategy objects
- Assigns new strategy_id (not inherited from Claude output)

### `test_executor.py`
- Kalshi fill timeout → FAILED state, no Robinhood order
- Kalshi fill → Robinhood failure → emergency Kalshi close triggered
- Successful round trip: IDLE → OPEN → CLOSED, PnL recorded
- Profit target exit fires at correct threshold
- Stop loss exit fires at correct threshold

### `test_evolution_cycle.py`
- Full evolution cycle with mocked Claude returning valid JSON: 4 new SHADOW strategies created
- Claude returns invalid JSON: 3 retries attempted, then cycle aborts without DB changes
- Shadow strategy with better fitness than worst live: promotion event emitted
- Condemned strategies archived only after trade_count >= 20

---

## SUCCESS CRITERIA

The project is considered successfully built when ALL of the following are true:

### SC-1: Test Suite Passes
```
pytest tests/ -v --tb=short
```
All tests green. Zero failures. Zero skips. Type checking passes:
```
mypy arbvoy/ --strict
```
Zero errors.

### SC-2: Dry Run Mode
Running `python run.py --dry-run` must:
- Connect to Kalshi WebSocket and receive at least one contract quote within 30 seconds
- Connect to Robinhood and receive a valid BTC spot price within 10 seconds
- Compute a model probability and log it (even if no trade signal fires)
- NOT submit any orders
- Run for 5 minutes without crashing, generating continuous log output

### SC-3: Signal Detection Verified
Given a manually constructed MarketSnapshot where:
- BTC spot = $97,000
- Kalshi contract: strike=$100,000, expiry=3 days, YES ask=$0.42
- Model probability at 60% annualized vol ≈ 0.295
- Implied probability = 0.42
- Edge = |0.42 - 0.295| = 12.5% = 1250 bps >> MIN_EDGE_BPS

The signal engine must emit a `buy_no` signal with edge_bps > 1000. This can be verified
via a unit test or a `--simulate-snapshot` CLI flag.

### SC-4: Risk Blocking Works
When daily PnL is manually set to -4% in the test DB, `python run.py --dry-run` must log
`[RISK_BLOCK] DAILY_LOSS_HALT` for every signal and submit zero orders.

### SC-5: Evolution Cycle Produces Valid Strategies
Running `python -m arbvoy.evolution.shinka --force-cycle` with a real ANTHROPIC_API_KEY
must produce exactly 4 new Strategy objects in the DB with status=SHADOW and valid JSON.
The cycle must complete in under 30 seconds.

### SC-6: Audit Log Is Human-Readable and Complete
Every executed trade (in paper/shadow mode) must produce log lines containing all of:
`[SIGNAL]`, `[RISK]`, `[ORDER]`, `[FILL]`, `[EXIT]` in sequence, each with the same
`trade_id` for traceability.

### SC-7: Graceful Shutdown
`SIGINT` (Ctrl-C) must:
- Cancel all pending open orders (log each cancellation)
- Write final state to DB
- Flush log buffer
- Exit with code 0

### SC-8: No Hardcoded Secrets
`grep -r "sk-ant\|kalshi\|ROBA" arbvoy/` must return zero matches.
All secrets loaded exclusively from environment / `.env` file.

---

## IMPLEMENTATION NOTES FOR CODEX

1. **Start with the data models and config** (`config.py`, all `models.py` files).
   Every other module depends on them. Get these right first.

2. **Build feeds as thin adapters** — their only job is to produce typed model objects.
   Implement `KalshiFeed` with a real WebSocket loop and `RobinhoodFeed` as a polling loop.
   Include realistic reconnect logic from day one.

3. **Implement the probability model with full test coverage** before wiring it to signals.
   The math must be correct — this is the core of the strategy.

4. **Wire the main loop in `orchestrator.py` last**, after all components have unit tests.

5. **The Anthropic API call in `shinka.py` must use `model="claude-sonnet-4-5"`.**
   Pass `max_tokens=2000`. Handle `anthropic.APIError` gracefully — log and skip cycle.

6. **All database writes must be atomic** — use `async with db.transaction()` for
   multi-row writes (e.g., closing a trade + writing audit event must be one transaction).

7. **Never log raw API keys or secrets** at any log level.

8. **Include a `--paper-trade` flag** in `run.py` that runs the full system but replaces
   `KalshiClient.submit_order` and `RobinhoodClient.submit_order` with mock fill functions
   that return simulated fills at the ask price. Paper mode should be the default for
   first run; live mode requires `--live` flag explicitly.

9. **The seed strategy (generation 0) is the safety net.** It must be conservative enough
   that it will not blow up the account even if signal quality is poor. Use the default
   values defined in the spec — they are calibrated to be cautious.

10. **README.md must include**: quickstart (setup + paper trade run), architecture diagram
    (ASCII is fine), description of each module, how to read the audit log, how to trigger
    manual evolution cycle, and the full list of environment variables.

---

*End of ArbitrageVoy Codex Prompt. Begin implementation.*
