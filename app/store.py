from __future__ import annotations

import sqlite3
from pathlib import Path


class EventStore:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def initialize(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS slack_events (
                    event_id TEXT PRIMARY KEY,
                    received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.commit()

    def record_event(self, event_id: str) -> bool:
        self.initialize()
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO slack_events (event_id) VALUES (?)",
                (event_id,),
            )
            connection.commit()
            return cursor.rowcount == 1

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database_path)

