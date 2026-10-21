import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from aptos_sdk.account import Account
from fastapi.testclient import TestClient

import blockword.app as web
from blockword.operator import load_operator
from blockword.database import PostgresGameLock
from blockword.hosting import public_origin


def test_vercel_assigned_origin_is_used_only_in_vercel(monkeypatch):
    for key in ('BLOCKWORD_PUBLIC_ORIGIN', 'RENDER_EXTERNAL_URL', 'VERCEL'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('VERCEL_URL', 'deployment.vercel.app')
    assert public_origin() is None
    monkeypatch.setenv('VERCEL', '1')
    assert public_origin() == 'https://deployment.vercel.app'


def test_operator_can_load_from_secret_without_creating_a_file(tmp_path, monkeypatch):
    owner = Account.generate()
    monkeypatch.setenv("BLOCKWORD_OPERATOR_KEY", str(owner.private_key))
    assert str(load_operator(tmp_path).address()) == str(owner.address())
    assert list(tmp_path.iterdir()) == []


def test_invalid_operator_secret_does_not_echo_its_value(tmp_path, monkeypatch):
    monkeypatch.setenv("BLOCKWORD_OPERATOR_KEY", "secret-that-must-not-appear")
    with pytest.raises(ValueError) as error:
        load_operator(tmp_path)
    assert "secret-that-must-not-appear" not in str(error.value)


def test_serverless_never_falls_back_to_local_sqlite(tmp_path, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("BLOCKWORD_PUBLIC_ORIGIN", "https://blockword.example")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(web, "DATA", tmp_path / "must-not-exist")
    with pytest.raises(ValueError, match="DATABASE_URL"):
        web.Service()
    assert not web.DATA.exists()


def test_serverless_checks_deployment_without_changing_the_chain(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import scripts.check_deployment as deployment_check
    service = SimpleNamespace(ready=True, deployment={"address": "0x1"},
        owner=Account.generate(), chain=SimpleNamespace(close=AsyncMock()),
        accounts=SimpleNamespace(close=AsyncMock()))
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setattr(web, "Service", lambda: service)
    check = AsyncMock()
    monkeypatch.setattr(deployment_check, "verify_deployment", check)
    with TestClient(web.app) as client:
        # the health probe should work before the full service is ready.
        assert check.await_count == 1
    service.chain.close.assert_awaited_once()
    service.accounts.close.assert_awaited_once()


def test_cancelled_lock_acquisition_closes_connection(monkeypatch):
    import threading
    class Connection:
        closed = False
        def close(self): self.closed = True
    connection, arrived, finish = Connection(), threading.Event(), threading.Event()
    lock = PostgresGameLock("not-a-real-dsn")
    def acquire():
        arrived.set()
        finish.wait(2)
        return connection
    monkeypatch.setattr(lock, "acquire", acquire)
    async def run():
        task = asyncio.create_task(lock.__aenter__())
        await asyncio.to_thread(arrived.wait, 2)
        task.cancel()
        finish.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert connection.closed
        assert not lock.local.locked()
    asyncio.run(run())
