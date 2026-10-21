import asyncio
from unittest.mock import AsyncMock
import pytest
from aptos_sdk.account import Account
from aptos_sdk.async_client import ResourceNotFound
from fastapi.testclient import TestClient
import blockword.app as web
from blockword.store import Store


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "DATA", tmp_path)
    with TestClient(web.app) as client:
        yield client


def test_no_setup_is_honest_and_no_secrets_in_config(client):
    config = client.get("/api/config").json()
    assert config["ready"] is False
    assert "private_key" not in str(config)
    assert client.post("/api/start", json={}).status_code == 503


def test_cross_site_requests_cannot_spend_demo_gas(client):
    response = client.post("/api/start", json={}, headers={"Origin": "https://unrelated.example"})
    assert response.status_code == 403
    assert client.get("/api/config", headers={"Host": "unrelated.example"}).status_code == 403


def test_browser_receives_csp_and_accessible_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert 'aria-live="polite"' in response.text
    assert client.get("/static/app.js").status_code == 200


def test_sessions_are_token_scoped_and_persist(tmp_path):
    store = Store(tmp_path)
    store.put("one", {"secret": "local"})
    assert Store(tmp_path).get("one") == {"secret": "local"}
    assert store.get("two") is None
    with store.connect() as db:
        assert db.execute("SELECT id FROM sessions").fetchone()[0] != "one"


def test_failed_funding_keeps_session_cookie_so_retry_cannot_create_extra_wallets(client):
    svc = web.app.state.service
    svc.ready = True
    svc.ensure_funded = AsyncMock(side_effect=RuntimeError("temporary network failure"))
    response = client.post("/api/start", json={})
    assert response.status_code == 503
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert svc.store.count() == 1
    assert client.post("/api/start", json={}).status_code == 503
    assert svc.store.count() == 1


def test_public_response_does_not_leak_answer_or_private_key(client):
    svc = web.app.state.service
    player = Account.generate()
    private = str(player.private_key)
    state = {"key": private, "secret": {"answer": "peers", "salt": "secret salt"}, "receipts": []}
    game = {"round_id": "1", "guesses": [], "feedback": [], "finished": False,
            "verified": False, "won": False, "answer": "0x", "commitment": "0x1234"}
    output = svc.public(state, game, None)
    assert output["answer"] is None
    assert "peers" not in str(output)
    assert private not in str(output)
    assert "secret salt" not in str(output)


def test_submitted_receipt_survives_timeout_and_recovers(client):
    svc = web.app.state.service
    state = {"receipts": [{"hash": "0x123", "status": "submitted", "kind": "guess"}]}
    class Network:
        async def transaction_by_hash(self, tx):
            return {"type": "pending_transaction"}
    class Chain:
        client = Network()
        wait = AsyncMock(side_effect=TimeoutError())
    svc.chain = Chain()
    # restore the fake before TestClient runs lifespan cleanup.
    async def close():
        pass
    svc.chain.close = close
    with pytest.raises(TimeoutError):
        asyncio.run(svc.settle_pending("token", state))
    assert state["receipts"][0]["status"] == "submitted"
    svc.chain.wait = AsyncMock(return_value={"version": "123", "gas_used": "7"})
    asyncio.run(svc.settle_pending("token", state))
    assert svc.store.get("token")["receipts"][0]["status"] == "confirmed"


def test_missing_sdk_resource_is_a_new_game_not_a_chain_failure(client):
    from types import SimpleNamespace
    svc = web.app.state.service
    svc.chain = SimpleNamespace(
        address="0x1", close=AsyncMock(),
        client=SimpleNamespace(account_resource=AsyncMock(side_effect=ResourceNotFound("missing", "Game"))))
    assert asyncio.run(svc.resource(Account.generate(), "Game")) is None


def test_game_gas_reservation_fits_the_funded_wallet():
    from blockword.chain import Chain
    game, publisher = Chain("0x1", max_gas_amount=20_000), Chain("0x1")
    try:
        config = game.client.client_config
        assert config.max_gas_amount * config.gas_unit_price < 5_000_000
        assert publisher.client.client_config.max_gas_amount == 100_000
    finally:
        asyncio.run(game.close())
        asyncio.run(publisher.close())
