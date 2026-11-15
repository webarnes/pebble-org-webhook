from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path


class DeliveryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS deliveries (
                    id TEXT PRIMARY KEY,
                    received_at INTEGER NOT NULL
                )
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def already_seen(self, delivery_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM deliveries WHERE id = ?", (delivery_id,)
            ).fetchone()
            return row is not None

    def remember(self, delivery_id: str, *, now: int | None = None) -> bool:
        """Insert the delivery id. Returns True if this is the first time."""
        received_at = int(time.time() if now is None else now)
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO deliveries (id, received_at) VALUES (?, ?)",
                    (delivery_id, received_at),
                )
            except sqlite3.IntegrityError:
                return False
            return True

    def forget(self, delivery_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM deliveries WHERE id = ?", (delivery_id,))

    def expire_older_than(self, max_age_seconds: int, *, now: int | None = None) -> None:
        cutoff = int(time.time() if now is None else now) - max_age_seconds
        with self._connect() as conn:
            conn.execute("DELETE FROM deliveries WHERE received_at < ?", (cutoff,))
