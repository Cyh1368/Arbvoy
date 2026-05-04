# Backtest Methods & Utilities

This document outlines the standard procedures for discovering market opportunities and performing backtests using the ArbitrageVoy system.

## 1. Finding Tickers for a Specific Date
Use `list_all_tickers_for_date.py` to identify tradeable contracts (Threshold or Between) for a specific calendar date. This utility filters by series and minimum volume.

**Command:**
```bash
python list_all_tickers_for_date.py YYYY-MM-DD [--series S1 S2] [--min-volume V]
```

*   **`YYYY-MM-DD`**: Target date for events.
*   **`--series`**: List of series tickers to search (defaults to `["KXBTC", "KXBTCD", "KXBTC15M"]`).
*   **`--min-volume`**: Minimum volume threshold (e.g., `0.01`).

---

## 2. Running a Standard Backtest
The `engine.py` file contains the `BacktestRunner`, which performs a simulation using the standard probability model and strategy logic.

**Command:**
```bash
python arbvoy/backtest/engine.py --kalshi-ticker "TICKER_NAME" [--robinhood-history-path "PATH"]
```

*   **`--kalshi-ticker`**: The specific contract ticker to backtest (e.g., `KXBTC-26FEB2517-B68750`).
*   **`--robinhood-history-path`**: (Optional) Path to a pre-existing CSV for spot price history. If omitted, the system will attempt to fetch data from Coingecko.

---

## 3. Running the Optimized Strategy (Claude Signal)
Use `backtest_claude.py` to execute backtests using the validated "Three-Gate Cascade" signal (vol-regime-adjusted thresholds, consistency checks, and spot velocity filters).

**Command:**
```bash
python backtest_claude.py
```

*   **Customization:** Edit the `tickers` list within `run_claude_backtest()` inside `backtest_claude.py` to target different tickers.
*   **Outputs:** This generates a folder for each ticker in `artifacts/claude_[ticker]/` containing a detailed `backtest_report.html` and PnL/signal tracking data.

---

## Operational Notes
*   **Output Directories:** All backtest artifacts, including charts and CSV reports, are saved to the `artifacts/` folder.
*   **Data Dependencies:** If the system fails due to missing spot history, `engine.py` and `backtest_claude.py` will attempt to auto-fetch the required BTC spot data from Coingecko. Ensure your network connection is stable during these fetches.
*   **Environment:** Ensure all dependencies (pandas, numpy, scipy) are installed per `pyproject.toml`.
