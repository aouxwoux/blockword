from unittest.mock import AsyncMock

import pytest
from aptos_sdk.account import Account
from fastapi.testclient import TestClient

import blockword.app as web
from blockword.hosting import public_origin


@pytest.fixture
def hosted(tmp_path, monkeypatch):
    monkeypatch.setenv("BLOCKWORD_PUBLIC_ORIGIN", "https://blockword.example")
    monkeypatch.setattr(web, "DATA", tmp_path)
    with TestClient(web.app, base_url="https://blockword.example") as client:
        yield client, web.app.state.service


@pytest.mark.parametrize("value", ["http://demo.example", "https://demo.example/path",
    "https://a:b@demo.example", "https://demo.example?next=evil", "https://demo.example#x",
    "https://demo.example:bad", "https://demo.example\n", "https://demo.example\\evil"])
def test_invalid_public_origin_fails_closed(monkeypatch, value):
    monkeypatch.setenv("BLOCKWORD_PUBLIC_ORIGIN", value)
    with pytest.raises(ValueError):
        public_origin()


def test_render_url_is_used_without_trusting_request_headers(monkeypatch):
    monkeypatch.delenv("BLOCKWORD_PUBLIC_ORIGIN", raising=False)
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://blockword.onrender.com")
    assert public_origin() == "https://blockword.onrender.com"


def test_public_host_and_cross_site_checks(hosted):
    client, _ = hosted
    assert client.get("/").status_code == 200
    assert client.get("/api/config", headers={"Host": "attacker.example"}).status_code == 403
    assert client.post("/api/start", headers={"Origin": "https://attacker.example"}).status_code == 403
    assert client.post("/api/start", headers={"Origin": "https://blockword.example",
        "Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get("/healthz", headers={"Host": "internal-probe"}).json() == {"status": "ok"}
    assert client.head("/healthz").status_code == 200


def test_proxy_cannot_change_wallet_origin_or_disable_secure_cookie(hosted):
    client, svc = hosted
    svc.accounts.client.info = AsyncMock(return_value={"chain_id": 249})
    wallet = Account.generate()
    # the proxy terminates TLS; the app sees HTTP but must use the public HTTPS origin.
    response = client.post("http://blockword.example/api/auth/challenge",
        json={"wallet_address": str(wallet.address())},
        headers={"Origin": "https://blockword.example", "X-Forwarded-Host": "attacker.example",
                 "X-Forwarded-Proto": "http"})
    assert response.status_code == 200
    assert "Application: https://blockword.example\n" in response.json()["message"]
    assert "attacker.example" not in response.json()["message"]
    assert "Secure" in response.headers["set-cookie"]


def test_hosted_demo_wallet_cookie_is_secure(hosted):
    client, svc = hosted
    svc.ready = True
    svc.ensure_funded = AsyncMock(side_effect=RuntimeError("offline"))
    response = client.post("/api/start", headers={"Origin": "https://blockword.example"})
    assert response.status_code == 503
    assert "Secure" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
