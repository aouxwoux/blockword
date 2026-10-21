import asyncio
import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aptos_sdk.account import Account

import scripts.check_deployment as deployment_check


NODE = "https://fullnode.devnet.aptoslabs.com/v1"
BYTECODE = bytes.fromhex("aabbccdd")


class ReadOnlyClient:
    def __init__(self, owner, *, chain_id=249, bytecode=BYTECODE, oracle_key=None):
        self.owner = owner
        self.chain_id = chain_id
        self.bytecode = bytecode
        self.oracle_key = oracle_key or owner.public_key().to_crypto_bytes()
        self.reads = []
        self.close = AsyncMock()

    async def info(self):
        self.reads.append(("info",))
        return {"chain_id": self.chain_id}

    async def account_module(self, address, module):
        self.reads.append(("account_module", address, module))
        return {"bytecode": "0x" + self.bytecode.hex()}

    async def account_resource(self, address, resource):
        self.reads.append(("account_resource", address, resource))
        return {"data": {"oracle_key": "0x" + self.oracle_key.hex()}}

    async def call(self, *args, **kwargs):
        raise AssertionError("read-only deployment check must not call a Move function")

    async def broadcast(self, *args, **kwargs):
        raise AssertionError("read-only deployment check must not broadcast")

    async def fund_player(self, *args, **kwargs):
        raise AssertionError("read-only deployment check must not fund an account")

    async def prepare_funding(self, *args, **kwargs):
        raise AssertionError("read-only deployment check must not prepare a funding transaction")

    async def submit_bcs_transaction(self, *args, **kwargs):
        raise AssertionError("read-only deployment check must not submit a transaction")


class FakeChain:
    def __init__(self, address, *, node, client):
        assert node == NODE
        self.address = address
        self.client = client

    async def close(self):
        await self.client.close()


def manifest_for(owner):
    return {
        "network": "devnet",
        "chain_id": 249,
        "address": str(owner.address()),
        "node_url": NODE,
        "module_bytecode_sha256": hashlib.sha256(BYTECODE).hexdigest(),
    }


def install_fake_chain(monkeypatch, owner, **client_kwargs):
    client = ReadOnlyClient(owner, **client_kwargs)
    monkeypatch.setattr(
        deployment_check,
        "Chain",
        lambda address, node: FakeChain(address, node=node, client=client),
    )
    return client


def test_verify_deployment_accepts_matching_state_and_only_reads(monkeypatch):
    owner = Account.generate()
    client = install_fake_chain(monkeypatch, owner)

    asyncio.run(deployment_check.verify_deployment(manifest_for(owner), owner))

    assert [call[0] for call in client.reads] == ["info", "account_module", "account_resource"]
    assert client.reads[1][1:] == (owner.address(), "game")
    assert client.reads[2][1:] == (
        owner.address(),
        f"{owner.address()}::game::Config",
    )
    client.close.assert_awaited_once()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("network", "mainnet", "devnet only"),
        ("address", "0x" + "11" * 32, "address do not match"),
        ("node_url", "https://example.invalid/v1", "expected devnet node"),
    ],
)
def test_verify_deployment_rejects_manifest_mismatch_before_network(monkeypatch, field, value, message):
    owner = Account.generate()
    monkeypatch.setattr(
        deployment_check,
        "Chain",
        lambda *args, **kwargs: pytest.fail("manifest mismatch must fail before client construction"),
    )
    manifest = manifest_for(owner)
    manifest[field] = value

    with pytest.raises(ValueError, match=message):
        asyncio.run(deployment_check.verify_deployment(manifest, owner))


@pytest.mark.parametrize(
    ("client_kwargs", "manifest_update", "message"),
    [
        ({"chain_id": 2}, {}, "chain ID changed"),
        ({"bytecode": b"different module"}, {}, "does not match the recorded deployment"),
        ({"oracle_key": bytes(32)}, {}, "referee key does not match"),
        ({}, {"module_bytecode_sha256": "0" * 64}, "does not match the recorded deployment"),
    ],
)
def test_verify_deployment_rejects_chain_mismatch_and_still_closes(
    monkeypatch, client_kwargs, manifest_update, message
):
    owner = Account.generate()
    client = install_fake_chain(monkeypatch, owner, **client_kwargs)
    manifest = manifest_for(owner)
    manifest.update(manifest_update)

    with pytest.raises(ValueError, match=message):
        asyncio.run(deployment_check.verify_deployment(manifest, owner))

    client.close.assert_awaited_once()
    assert all(call[0] not in {"call", "broadcast", "submit_bcs_transaction"} for call in client.reads)


@pytest.mark.parametrize("missing", ["deployment.json", "deployer.json"])
def test_check_rejects_incomplete_local_setup(tmp_path, monkeypatch, missing):
    monkeypatch.setattr(deployment_check, "ROOT", tmp_path)
    data = tmp_path / "private-data"
    data.mkdir()
    (tmp_path / "deployment.json").write_text("{}", encoding="utf-8")
    (data / "deployer.json").write_text("{}", encoding="utf-8")
    (tmp_path / missing).unlink() if missing == "deployment.json" else (data / missing).unlink()
    monkeypatch.setattr(
        deployment_check,
        "verify_deployment",
        AsyncMock(side_effect=AssertionError("incomplete setup must fail before verification")),
    )

    with pytest.raises(ValueError, match="Local setup is incomplete"):
        asyncio.run(deployment_check.check(data))


def test_check_loads_local_key_and_manifest_then_verifies_them(tmp_path, monkeypatch):
    monkeypatch.setattr(deployment_check, "ROOT", tmp_path)
    data = tmp_path / "private-data"
    data.mkdir()
    owner = Account.generate()
    owner.store(str(data / "deployer.json"))
    (tmp_path / "deployment.json").write_text(json.dumps(manifest_for(owner)), encoding="utf-8")
    verify = AsyncMock()
    monkeypatch.setattr(deployment_check, "verify_deployment", verify)

    asyncio.run(deployment_check.check(data))

    verify.assert_awaited_once()
    args = verify.await_args.args
    assert args[0] == manifest_for(owner)
    assert str(args[1].address()) == str(owner.address())
