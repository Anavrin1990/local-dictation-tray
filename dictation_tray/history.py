from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    id: int
    created_at: str
    text: str
    duration_seconds: float
    language: str | None


class HistoryRepository:
    def __init__(self, path: Path):
        self.path = path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS dictations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at TEXT NOT NULL,
                        text TEXT NOT NULL,
                        duration_seconds REAL NOT NULL,
                        language TEXT
                    )"""
                )
                connection.execute("CREATE INDEX IF NOT EXISTS idx_dictations_created ON dictations(created_at DESC)")

    def add(self, text: str, duration_seconds: float, language: str | None, limit: int) -> HistoryEntry:
        normalized = " ".join(text.split())
        if not normalized:
            raise ValueError("Нельзя сохранить пустую диктовку")
        self._validate_limit(limit)
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with closing(self._connect()) as connection:
            with connection:
                cursor = connection.execute(
                    "INSERT INTO dictations(created_at, text, duration_seconds, language) VALUES (?, ?, ?, ?)",
                    (created_at, normalized, duration_seconds, language),
                )
                self._trim_connection(connection, limit)
        return HistoryEntry(cursor.lastrowid, created_at, normalized, duration_seconds, language)

    def trim_to_limit(self, limit: int) -> None:
        """Immediately apply a newly saved history limit to existing entries."""
        self._validate_limit(limit)
        with closing(self._connect()) as connection:
            with connection:
                self._trim_connection(connection, limit)

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if limit < 1:
            raise ValueError("Лимит истории должен быть положительным")

    @staticmethod
    def _trim_connection(connection: sqlite3.Connection, limit: int) -> None:
        connection.execute(
            "DELETE FROM dictations WHERE id NOT IN (SELECT id FROM dictations ORDER BY id DESC LIMIT ?)",
            (limit,),
        )

    def list_recent(self, limit: int = 200) -> list[HistoryEntry]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT id, created_at, text, duration_seconds, language FROM dictations ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [HistoryEntry(**dict(row)) for row in rows]

    def delete_all(self) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("DELETE FROM dictations")
