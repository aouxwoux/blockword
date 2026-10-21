import asyncio
from unittest.mock import AsyncMock

import pytest
from aptos_sdk.account import Account
from aptos_sdk.async_client import ApiError
from fastapi.testclient import TestClient

import blockword.app as web


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "DATA", tmp_path)
    with TestClient(web.app) as test_client:
        yield test_client


class AcceptedThenTimedOutChain:
    """the node accepted the transaction, then the response was lost."""

    address = "0x1"

    def __init__(self, store, token):
        self.store = store
        self.token = token
        self.prepared = {
            "hash": "0xabc123",
            "signed_bcs": "01020304",
            "expires_at": 1_900_000_000,
        }
        self.prepare = AsyncMock(return_value=self.prepared)
        self.broadcast = AsyncMock(side_effect=self._broadcast)
        self.lookups = 0
        self.client = self
        self.close = AsyncMock()

    async def _broadcast(self, prepared):
        # the journal must be committed before submission.
        saved = self.store.get(self.token)
        assert saved["receipts"][0]["hash"] == prepared["hash"]
        assert saved["receipts"][0]["signed_bcs"] == prepared["signed_bcs"]
        raise TimeoutError("submit response was lost")

    async def transaction_by_hash(self, tx_hash):
        assert tx_hash == self.prepared["hash"]
        self.lookups += 1
        if self.lookups == 1:
            raise ApiError("not indexed yet", 404)
        return {
            "type": "user_transaction",
            "success": True,
            "version": "42",
            "gas_used": "7",
        }

    async def wait(self, tx_hash):
        raise AssertionError("recovery should resolve the saved hash before waiting")


def test_intent_is_saved_before_broadcast_and_retry_uses_saved_hash(client):
    svc = web.app.state.service
    token = "offline-recovery-token"
    player = Account.generate()
    state = {"key": str(player.private_key), "receipts": [], "secret": None}
    svc.store.put(token, state)
    chain = AcceptedThenTimedOutChain(svc.store, token)
    svc.chain = chain
    svc.ensure_funded = AsyncMock()

    with pytest.raises(TimeoutError, match="submit response was lost"):
        asyncio.run(svc.transact(token, state, player, "guess", b"peers", b"\x00" * 5))

    journaled = svc.store.get(token)["receipts"][0]
    assert journaled["status"] == "submitted"
    assert journaled["hash"] == chain.prepared["hash"]
    assert journaled["signed_bcs"] == chain.prepared["signed_bcs"]

    # recovery finds the saved hash instead of signing another transaction.
    asyncio.run(svc.settle_pending(token, state))
    assert svc.store.get(token)["receipts"][0]["status"] == "confirmed"
    chain.prepare.assert_awaited_once()
    chain.broadcast.assert_awaited_once()

    public = svc.public(state, None, None)
    assert chain.prepared["signed_bcs"] not in str(public)


def test_failed_executed_receipt_is_persisted(client):
    svc = web.app.state.service
    token = "offline-failed-receipt"
    player = Account.generate()
    state = {
        "key": str(player.private_key),
        "secret": None,
        "receipts": [{
            "hash": "0xdead",
            "signed_bcs": "aabbcc",
            "expires_at": 1_900_000_000,
            "kind": "guess",
            "status": "submitted",
        }],
    }
    svc.store.put(token, state)

    class FailedChain:
        client = None

        def __init__(self):
            self.client = self
            self.close = AsyncMock()
            self.wait = AsyncMock()

        async def transaction_by_hash(self, tx_hash):
            assert tx_hash == "0xdead"
            return {
                "type": "user_transaction",
                "success": False,
                "version": "43",
                "gas_used": "6",
            }

    svc.chain = FailedChain()
    with pytest.raises(RuntimeError, match="transaction failed"):
        asyncio.run(svc.settle_pending(token, state))

    persisted = svc.store.get(token)["receipts"][0]
    assert persisted["status"] == "failed"
    assert persisted["signed_bcs"] == "aabbcc"


def test_missing_round_backup_is_read_only_on_state_and_recovery_returns_409(client):
    svc = web.app.state.service
    player = Account.generate()
    token = "offline-missing-backup"
    state = {"key": str(player.private_key), "secret": None, "receipts": []}
    svc.store.put(token, state)
    svc.ready = True

    game = {
        "round_id": "1",
        "guesses": [],
        "feedback": [],
        "finished": True,
        "verified": False,
        "won": False,
        "answer": "0x",
        "commitment": "0x" + "11" * 32,
    }
    passport = {"rounds": "0", "verified_rounds": "0", "wins": "0", "total_guesses": "0"}

    class ReadOnlyChain:
        address = "0x1"

        def __init__(self):
            self.close = AsyncMock()
            self.prepare = AsyncMock(side_effect=AssertionError("must not prepare a reveal"))
            self.broadcast = AsyncMock(side_effect=AssertionError("must not broadcast a reveal"))
            self.client = self

        async def account_resource(self, _address, resource_type):
            if resource_type.endswith("::Game"):
                return {"data": game}
            if resource_type.endswith("::Passport"):
                return {"data": passport}
            raise AssertionError(resource_type)

    chain = ReadOnlyChain()
    svc.chain = chain
    original_put = svc.store.put
    writes = []

    def track_put(write_token, write_state):
        writes.append((write_token, write_state.copy()))
        return original_put(write_token, write_state)

    svc.store.put = track_put
    client.cookies.set(web.COOKIE, token)

    state_response = client.get("/api/state")
    assert state_response.status_code == 200
    assert state_response.json()["finished"] is True
    assert writes == []

    recovery_response = client.post("/api/recover", json={})
    assert recovery_response.status_code == 409
    assert "Restore the original local data directory" in recovery_response.json()["detail"]
    assert writes == []
    assert svc.store.get(token)["secret"] is None
    chain.prepare.assert_not_awaited()
    chain.broadcast.assert_not_awaited()
