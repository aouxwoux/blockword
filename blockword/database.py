import asyncio
import sqlite3

import psycopg
from psycopg.rows import dict_row

SQL_LOCK = 0x424C4F4353514C
GAME_LOCK = 0x424C4F4347414D


def connect_postgres(url):
    return psycopg.connect(url, connect_timeout=10, prepare_threshold=None)


class PostgresConnection:
    """adapt the sqlite statements without changing parameter binding."""
    def __init__(self, connection):
        self.connection = connection
        self.row_factory = None

    def execute(self, sql, parameters=()):
        if sql == "BEGIN IMMEDIATE":
            # Store.connect already holds the transaction and SQL lock.
            return None
        cursor = self.connection.cursor(row_factory=dict_row if self.row_factory == sqlite3.Row else None)
        return cursor.execute(sql.replace("?", "%s"), parameters)

    def executescript(self, script):
        # only used for the fixed table and index schema, never user input.
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)


class PostgresGameLock:
    """keep game requests in order while journal writes commit separately.

    use a transaction lock here; session locks do not work with Neon transaction pooling.
    """
    def __init__(self, url):
        self.url = url
        self.local = asyncio.Lock()
        self.connection = None

    def acquire(self):
        connection = connect_postgres(self.url)
        try:
            connection.execute("SET LOCAL lock_timeout = '10s'")
            connection.execute("SET LOCAL idle_in_transaction_session_timeout = '120s'")
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (GAME_LOCK,))
            return connection
        except BaseException:
            connection.close()
            raise

    async def __aenter__(self):
        await self.local.acquire()
        pending = asyncio.create_task(asyncio.to_thread(self.acquire))
        try:
            self.connection = await asyncio.shield(pending)
        except asyncio.CancelledError:
            # cancellation does not stop the background thread, so close its lock connection too.
            try:
                connection = await pending
                connection.close()
            finally:
                self.local.release()
            raise
        except BaseException:
            self.local.release()
            raise
        return self

    async def __aexit__(self, *_):
        try:
            # closing releases the lock; game writes commit on separate connections.
            self.connection.close()
        finally:
            self.connection = None
            self.local.release()
