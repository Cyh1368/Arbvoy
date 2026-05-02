# ArbitrageVoy

ArbitrageVoy is an event-driven Python trading system for probability mispricing arbitrage
between BTC prediction market contracts and BTC spot.

## Quickstart

1. Create a virtual environment and install dependencies.
2. Copy `.env.example` to `.env` and fill in credentials.
3. Run paper mode:

```bash
python run.py --paper-trade
```

4. Run a dry-run snapshot check:

```bash
python run.py --dry-run
```

## Architecture

```text
feeds -> signals -> risk -> execution -> journal
                   \-> strategy registry -> evolution
                          \-> audit logger
```

## Modules

- `arbvoy.config`: environment-backed settings.
- `arbvoy.feeds`: market data adapters.
- `arbvoy.signals`: probability model, volatility estimate, opportunity generation.
- `arbvoy.strategy`: strategy schema, registry, and selection.
- `arbvoy.risk`: pre-trade risk checks.
- `arbvoy.execution`: dual-leg order coordination.
- `arbvoy.journal`: SQLite persistence.
- `arbvoy.evolution`: fitness scoring and strategy evolution.
- `arbvoy.audit`: console and JSONL logging.
- `arbvoy.orchestrator`: main loop wiring.

## Audit Log

The audit log is written to `LOG_FILE_PATH` in JSONL format and to the console in a compact
human-readable format. Key events include `SIGNAL`, `RISK_BLOCK`, `ORDER`, `FILL`, `EXIT`,
and `EVOLVE`.

## Manual Evolution

Run one evolution cycle explicitly:

```bash
python -m arbvoy.evolution.shinka --force-cycle
```

## Environment Variables

- `KALSHI_API_KEY`
- `KALSHI_API_SECRET`
- `ROBINHOOD_API_KEY`
- `ROBINHOOD_ACCOUNT_NUMBER`
- `ANTHROPIC_API_KEY`
- `KALSHI_BASE_URL`
- `KALSHI_WS_URL`
- `ROBINHOOD_BASE_URL`
- `SNAPSHOT_INTERVAL_SECONDS`
- `RING_BUFFER_SIZE`
- `MIN_EDGE_BPS`
- `MIN_KALSHI_VOLUME_24H`
- `MAX_KALSHI_NOTIONAL_PER_CONTRACT`
- `MAX_TOTAL_KALSHI_NOTIONAL`
- `MAX_ROBINHOOD_HEDGE_NOTIONAL`
- `DAILY_LOSS_LIMIT_PCT`
- `STOP_LOSS_BPS`
- `PROFIT_TARGET_BPS`
- `TIME_EXIT_HOURS`
- `KELLY_FRACTION`
- `EVOLUTION_TRADE_INTERVAL`
- `SHADOW_TRADE_COUNT`
- `STRATEGY_POPULATION_SIZE`
- `LOG_FILE_PATH`
- `DB_PATH`

