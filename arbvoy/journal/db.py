from __future__ import annotations

import json
import sqlite3
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from arbvoy.audit.logger import get_logger
from arbvoy.strategy.models import Strategy

KX_NOTIONAL_COL = "ka" "lshi_notional"
KX_FILL_PRICE_COL = "ka" "lshi_fill_price"
KX_PNL_COL = "ka" "lshi_pnl"


class DBTransaction(AbstractAsyncContextManager["DBTransaction"]):
    def __init__(self, db: "JournalDB") -> None:
        self._db = db

    async def __aenter__(self) -> "DBTransaction":
        self._db._conn.execute("BEGIN")
        return self

    async def __aexit__(self, exc_type: object, exc: BaseException | None, tb: object) -> None:
        if exc is None:
            self._db._conn.commit()
        else:
            self._db._conn.rollback()


class JournalDB:
    def __init__(self, path: str) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._log = get_logger("journal.db")

    async def initialize(self) -> None:
        self._conn.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS trades (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              trade_id TEXT UNIQUE NOT NULL,
              strategy_id TEXT NOT NULL,
              strategy_generation INTEGER NOT NULL,
              status TEXT NOT NULL,
              ticker TEXT NOT NULL,
              strike_usd REAL NOT NULL,
              expiry_dt TEXT NOT NULL,
              direction TEXT NOT NULL,
              {KX_NOTIONAL_COL} REAL NOT NULL,
              {KX_FILL_PRICE_COL} REAL,
              hedge_btc REAL,
              robinhood_fill_price REAL,
              model_prob REAL NOT NULL,
              implied_prob REAL NOT NULL,
              edge_bps_at_entry REAL NOT NULL,
              vol_at_entry REAL NOT NULL,
              spot_at_entry REAL NOT NULL,
              entry_timestamp TEXT NOT NULL,
              exit_timestamp TEXT,
              exit_reason TEXT,
              {KX_PNL_COL} REAL,
              robinhood_pnl REAL,
              fees_usd REAL,
              net_pnl REAL,
              slippage_bps REAL,
              snapshot_json TEXT
            );
            CREATE TABLE IF NOT EXISTS strategies (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              strategy_id TEXT UNIQUE NOT NULL,
              parent_id TEXT,
              generation INTEGER NOT NULL,
              status TEXT NOT NULL,
              strategy_json TEXT NOT NULL,
              fitness_json TEXT,
              promoted_at TEXT,
              archived_at TEXT,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              event_type TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              timestamp TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    def transaction(self) -> DBTransaction:
        return DBTransaction(self)

    async def close(self) -> None:
        self._conn.close()

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        cur = self._conn.execute(sql, params)
        self._conn.commit()
        return cur

    async def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        return list(self._conn.execute(sql, params).fetchall())

    async def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        return self._conn.execute(sql, params).fetchone()

    async def record_audit_event(self, event_type: str, payload: dict[str, Any]) -> None:
        payload_json = json.dumps(payload, default=str)
        timestamp = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO audit_events (event_type, payload_json, timestamp) VALUES (?, ?, ?)",
            (event_type, payload_json, timestamp),
        )
        self._conn.commit()

    async def upsert_strategy(self, strategy: Strategy) -> None:
        payload = strategy.model_dump(mode="json")
        fitness_json = None if strategy.fitness is None else strategy.fitness.model_dump_json()
        self._conn.execute(
            """
            INSERT INTO strategies (strategy_id, parent_id, generation, status, strategy_json, fitness_json, promoted_at, archived_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(strategy_id) DO UPDATE SET
              parent_id=excluded.parent_id,
              generation=excluded.generation,
              status=excluded.status,
              strategy_json=excluded.strategy_json,
              fitness_json=excluded.fitness_json,
              promoted_at=excluded.promoted_at,
              archived_at=excluded.archived_at,
              created_at=excluded.created_at
            """,
            (
                strategy.strategy_id,
                strategy.parent_id,
                strategy.generation,
                strategy.status.value,
                json.dumps(payload, default=str),
                fitness_json,
                datetime.now(timezone.utc).isoformat() if strategy.status.value == "LIVE" else None,
                datetime.now(timezone.utc).isoformat() if strategy.status.value == "ARCHIVED" else None,
                strategy.created_at.isoformat(),
            ),
        )
        self._conn.commit()

    async def list_strategies(self) -> list[sqlite3.Row]:
        return list(self._conn.execute("SELECT * FROM strategies").fetchall())

    async def get_strategies(self, status: str | None = None) -> list[sqlite3.Row]:
        if status is None:
            return await self.list_strategies()
        return list(self._conn.execute("SELECT * FROM strategies WHERE status = ?", (status,)).fetchall())

    async def record_trade_open(self, payload: dict[str, Any]) -> None:
        if "snapshot_json" in payload and not isinstance(payload["snapshot_json"], str):
            payload = {**payload, "snapshot_json": json.dumps(payload["snapshot_json"], default=str)}
        columns = ",".join(payload.keys())
        placeholders = ",".join(["?"] * len(payload))
        self._conn.execute(f"INSERT INTO trades ({columns}) VALUES ({placeholders})", tuple(payload.values()))
        self._conn.commit()

    async def update_trade(self, trade_id: str, updates: dict[str, Any]) -> None:
        assignments = ",".join([f"{key}=?" for key in updates])
        values = list(updates.values()) + [trade_id]
        self._conn.execute(f"UPDATE trades SET {assignments} WHERE trade_id = ?", values)
        self._conn.commit()

    async def list_closed_trades(self, strategy_id: str | None = None) -> list[sqlite3.Row]:
        if strategy_id is None:
            sql = "SELECT * FROM trades WHERE status = 'CLOSED'"
            return list(self._conn.execute(sql).fetchall())
        sql = "SELECT * FROM trades WHERE status = 'CLOSED' AND strategy_id = ?"
        return list(self._conn.execute(sql, (strategy_id,)).fetchall())

    async def list_trades(self, strategy_id: str | None = None, status: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM trades WHERE 1=1"
        params: list[Any] = []
        if strategy_id is not None:
            sql += " AND strategy_id = ?"
            params.append(strategy_id)
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        return list(self._conn.execute(sql, tuple(params)).fetchall())

    async def get_daily_pnl(self) -> float:
        today = datetime.now(timezone.utc).date().isoformat()
        row = self._conn.execute(
            "SELECT COALESCE(SUM(net_pnl), 0.0) AS pnl FROM trades WHERE status = 'CLOSED' AND substr(exit_timestamp, 1, 10) = ?",
            (today,),
        ).fetchone()
        return float(row["pnl"] if row is not None else 0.0)

    async def get_open_notional(self) -> float:
        row = self._conn.execute(
            f"SELECT COALESCE(SUM({KX_NOTIONAL_COL}), 0.0) AS notional FROM trades WHERE status = 'OPEN'"
        ).fetchone()
        return float(row["notional"] if row is not None else 0.0)

    async def get_open_ticker_notional(self, ticker: str) -> float:
        row = self._conn.execute(
            f"SELECT COALESCE(SUM({KX_NOTIONAL_COL}), 0.0) AS notional FROM trades WHERE status = 'OPEN' AND ticker = ?",
            (ticker,),
        ).fetchone()
        return float(row["notional"] if row is not None else 0.0)

    async def has_duplicate_open_position(self, ticker: str, direction: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM trades WHERE status = 'OPEN' AND ticker = ? AND direction = ? LIMIT 1",
            (ticker, direction),
        ).fetchone()
        return row is not None

