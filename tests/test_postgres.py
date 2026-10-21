"""use a disposable postgres database via BLOCKWORD_TEST_DATABASE_URL."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
import uuid

from aptos_sdk.account import Account
from aptos_sdk.async_client import ApiError
import psycopg
from psycopg.conninfo import make_conninfo
from psycopg import sql
import pytest

from blockword.accounts import Accounts, AccountError
from blockword.database import PostgresGameLock
from blockword.store import Store

BASE = os.getenv("BLOCKWORD_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not BASE, reason="A disposable Postgres database was not configured")


@pytest.fixture
def database():
    schema = "blockword_test_" + uuid.uuid4().hex
    with psycopg.connect(BASE) as db:
        db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        yield make_conninfo(BASE, options=f"-csearch_path={schema}")
    finally:
        with psycopg.connect(BASE) as db:
            db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


class Node:
    async def info(self): return {"chain_id": 249}
    async def account(self, _): raise ApiError("New account", 404)
    async def close(self): pass


def signed(wallet, request):
    full = f"APTOS\nnonce: {request['nonce']}\nmessage: {request['message']}"
    return {"challenge_id": request["challenge_id"], "public_key": str(wallet.public_key()),
            "full_message": full, "signature": str(wallet.sign(full.encode()))}


def login(accounts, wallet, actor="test"):
    async def run():
        request, binding = await accounts.challenge(str(wallet.address()), "https://demo.example", actor)
        return await accounts.verify(signed(wallet, request), binding, "https://demo.example", actor, "test")
    return asyncio.run(run())


def test_another_instance_reads_answer_backups_and_signed_transaction_journal(database, tmp_path):
    first = Store(tmp_path / "one", database)
    state = {"key": "demo-key", "secret": {"answer": "peers", "salt": "private"},
             "receipts": [{"signed_bcs": "00", "hash": "0xabc", "status": "submitted"}]}
    first.put("browser-token", state)
    second = Store(tmp_path / "two", database)
    assert second.get("browser-token") == state
    assert second.get("different-token") is None
    assert not (tmp_path / "one").exists()
    with second.connect() as db:
        assert db.execute("SELECT id FROM sessions").fetchone()[0] != "browser-token"


def test_database_errors_roll_back_and_close_connections(database, tmp_path):
    store = Store(tmp_path, database)
    with pytest.raises(RuntimeError):
        with store.connect() as db:
            db.execute("INSERT INTO sessions VALUES ('rollback-me','{}')")
            raise RuntimeError("Interrupted")
    assert db.connection.closed
    assert store.count() == 0


def test_profiles_history_and_revocation_survive_an_instance_restart(database, tmp_path):
    first = Accounts(Store(tmp_path / "one", database), client=Node())
    player, token, _ = login(first, Account.generate())
    first.rename(token, "Lead demo")
    first.store.put("demo-token", {"secret": {"answer": "peers"}, "receipts": []})
    first.link_demo(token, "demo-token")
    snapshot = {"player": "0x1", "round_id": 1, "board": [], "finished": True,
                "verified": True, "won": True, "answer": "peers", "definition": "Peers", "commitment": "0xabc"}
    first.save_round("demo-token", {"address": "0x2", "chain_id": 249}, snapshot)
    first.save_round("demo-token", {"address": "0x2", "chain_id": 249}, snapshot)
    first.store.put("demo-token", {"secret": None, "receipts": []})
    second = Accounts(Store(tmp_path / "two", database), client=Node())
    assert second.me(token)["id"] == player["id"]
    assert second.me(token)["display_name"] == "Lead demo"
    assert second.rounds(token, 20, 0)["total"] == 1
    assert second.rounds(token, 20, 0)["items"][0]["answer"] == "peers"
    second.revoke(token, all_sessions=True)
    with pytest.raises(AccountError): first.me(token)


def test_two_instances_cannot_consume_the_same_challenge(database, tmp_path):
    first = Accounts(Store(tmp_path / "one", database), client=Node())
    second = Accounts(Store(tmp_path / "two", database), client=Node())
    wallet = Account.generate()
    request, binding = asyncio.run(first.challenge(str(wallet.address()), "https://demo.example", "test"))
    payload = signed(wallet, request)
    def attempt(accounts):
        try:
            return asyncio.run(accounts.verify(payload, binding, "https://demo.example", "test", "test"))
        except AccountError as error:
            return error
    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(attempt, (first, second)))
    assert sum(isinstance(result, AccountError) for result in results) == 1
    assert sum(isinstance(result, tuple) for result in results) == 1


def test_concurrent_logins_share_one_profile(database, tmp_path):
    accounts = [Accounts(Store(tmp_path / str(i), database), client=Node()) for i in range(2)]
    wallet = Account.generate()
    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(lambda item: login(item, wallet), accounts))
    assert results[0][0]["id"] == results[1][0]["id"]
    assert len(accounts[0].sessions(results[0][1])) == 2


def test_game_lock_serializes_instances_and_releases_after_failure(database):
    async def run():
        first, second = PostgresGameLock(database), PostgresGameLock(database)
        acquired = asyncio.Event()
        async def worker():
            async with second:
                acquired.set()
        with pytest.raises(RuntimeError):
            async with first:
                task = asyncio.create_task(worker())
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(acquired.wait(), 0.2)
                raise RuntimeError("Request interrupted")
        await asyncio.wait_for(task, 5)
        assert acquired.is_set()
        assert first.connection is None and second.connection is None
    asyncio.run(run())
