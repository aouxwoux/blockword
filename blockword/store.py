import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, directory: Path, database_url: str | None = None):
        self.database_url = database_url or os.getenv("DATABASE_URL")
        self.path = None
        if not self.database_url:
            directory.mkdir(parents=True, exist_ok=True)
            self.path = directory / "sessions.sqlite3"
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
        if self.path:
            try:
                self.path.chmod(0o600)
            except OSError:
                pass

    @contextmanager
    def connect(self):
        if self.database_url:
            from .database import connect_postgres, PostgresConnection, SQL_LOCK
            with connect_postgres(self.database_url) as connection:
                connection.execute("SET LOCAL lock_timeout = '10s'")
                connection.execute("SET LOCAL statement_timeout = '15s'")
                connection.execute("SELECT pg_advisory_xact_lock(%s)", (SQL_LOCK,))
                yield PostgresConnection(connection)
            return
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=5000")
            with db:
                yield db
        finally:
            db.close()

    def game_lock(self):
        if self.database_url:
            from .database import PostgresGameLock
            return PostgresGameLock(self.database_url)
        import asyncio
        return asyncio.Lock()

    @staticmethod
    def digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def get(self, token: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT body FROM sessions WHERE id=?", (self.digest(token),)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, token: str, state: dict):
        with self.connect() as db:
            db.execute("INSERT INTO sessions VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
                       (self.digest(token), json.dumps(state)))

    def count(self) -> int:
        with self.connect() as db:
            return db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
