"""SQLite-backed persistence for open positions and trade history."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import List, Optional


class StateDB:
    """Simple SQLite wrapper storing open positions and trades."""

    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self._setup()

    def _setup(self):
        c = self.conn.cursor()
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS positions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT, side TEXT, entry_price REAL,
                qty_initial REAL, qty_remaining REAL,
                stop REAL, take REAL,
                r_value REAL, entry_time TEXT, broker TEXT,
                last_trade_time TEXT
            );
            CREATE TABLE IF NOT EXISTS trades(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT, side TEXT, entry_price REAL, exit_price REAL,
                qty REAL, pnl REAL, r_mult REAL,
                entry_time TEXT, exit_time TEXT, reason TEXT, broker TEXT
            );
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
            """
        )
        self.conn.commit()

    def save_position(self, pos: dict) -> int:
        c = self.conn.cursor()
        c.execute(
            """
            INSERT INTO positions 
            (symbol, side, entry_price, qty_initial, qty_remaining, stop, take, r_value, entry_time, broker, last_trade_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pos["symbol"],
                pos["side"],
                pos["entry"],
                pos["qty"],
                pos["qty"],
                pos["stop"],
                pos["target"],
                pos["r"],
                datetime.now(timezone.utc).isoformat(),
                pos["broker"],
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.conn.commit()
        return c.lastrowid

    def update_position(self, pos_id: int, new_stop: float):
        c = self.conn.cursor()
        c.execute("UPDATE positions SET stop = ? WHERE id = ?", (new_stop, pos_id))
        self.conn.commit()

    def close_position(
        self, pos_id: int, exit_price: float, pnl: float, r_mult: float, reason: str
    ):
        c = self.conn.cursor()
        pos = c.execute("SELECT * FROM positions WHERE id = ?", (pos_id,)).fetchone()
        if pos:
            c.execute(
                """
                INSERT INTO trades 
                (symbol, side, entry_price, exit_price, qty, pnl, r_mult, entry_time, exit_time, reason, broker)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pos["symbol"],
                    pos["side"],
                    pos["entry_price"],
                    exit_price,
                    pos["qty_remaining"],
                    pnl,
                    r_mult,
                    pos["entry_time"],
                    datetime.now(timezone.utc).isoformat(),
                    reason,
                    pos["broker"],
                ),
            )
            c.execute("DELETE FROM positions WHERE id = ?", (pos_id,))
            self.conn.commit()

    def get_open_positions(self) -> List[dict]:
        c = self.conn.cursor()
        rows = c.execute("SELECT * FROM positions").fetchall()
        return [dict(row) for row in rows]

    def get_all_trades(self) -> List[dict]:
        c = self.conn.cursor()
        rows = c.execute("SELECT * FROM trades ORDER BY exit_time").fetchall()
        return [dict(row) for row in rows]

    def get_last_trade_time(self, symbol: str) -> Optional[datetime]:
        """Get last trade time for a symbol"""
        c = self.conn.cursor()
        row = c.execute(
            "SELECT exit_time FROM trades WHERE symbol = ? ORDER BY exit_time DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        if row:
            return datetime.fromisoformat(row["exit_time"])
        return None


__all__ = ["StateDB"]
