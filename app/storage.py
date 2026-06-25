from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from app.models import Signal


class Storage:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    shares INTEGER NOT NULL,
                    price REAL,
                    rule_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    triggered_at TEXT NOT NULL,
                    raw_metrics_json TEXT NOT NULL,
                    notified INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_signals_dedup
                ON signals(symbol, rule_id, triggered_at, notified)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL
                )
                """
            )

    def save_run(self, status: str, message: str, run_at: datetime | None = None) -> int:
        now = run_at or datetime.now().astimezone()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO runs(run_at, status, message) VALUES (?, ?, ?)",
                (now.isoformat(timespec="seconds"), status, message),
            )
            return int(cur.lastrowid)

    def save_signal(self, signal: Signal, notified: bool = False) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO signals(
                    symbol, name, action, shares, price, rule_id, reason,
                    triggered_at, raw_metrics_json, notified
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal.symbol,
                    signal.name,
                    signal.action,
                    signal.shares,
                    signal.price,
                    signal.rule_id,
                    signal.reason,
                    signal.triggered_at.isoformat(timespec="seconds"),
                    json.dumps(signal.raw_metrics, ensure_ascii=False, default=str),
                    1 if notified else 0,
                ),
            )
            return int(cur.lastrowid)

    def mark_signal_notified(self, signal_id: int) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE signals SET notified = 1 WHERE id = ?", (signal_id,))

    def has_notified_today(self, symbol: str, rule_id: str, day: datetime) -> bool:
        day_prefix = day.date().isoformat()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM signals
                WHERE symbol = ?
                  AND rule_id = ?
                  AND notified = 1
                  AND substr(triggered_at, 1, 10) = ?
                LIMIT 1
                """,
                (symbol, rule_id, day_prefix),
            ).fetchone()
            return row is not None

    def latest_signals(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM signals ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
