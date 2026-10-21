import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from aptos_sdk.account import Account
from blockword.chain import Chain
from blockword.operator import load_operator


async def verify_deployment(manifest: dict, owner: Account) -> None:
    address = str(owner.address())
    if manifest.get("network") != "devnet":
        raise ValueError("This prototype is configured for Aptos devnet only.")
    if manifest.get("address") != address:
        raise ValueError("The saved deployer and deployment address do not match.")
    node_url = manifest.get("node_url")
    if node_url != "https://fullnode.devnet.aptoslabs.com/v1":
        raise ValueError("The deployment file does not name the expected devnet node.")
    chain = Chain(address, node=node_url)
    try:
        ledger = await chain.client.info()
        if int(ledger["chain_id"]) != int(manifest["chain_id"]):
            raise ValueError("The devnet chain ID changed. Check the recorded deployment before playing.")
        module = await chain.client.account_module(owner.address(), "game")
        digest = hashlib.sha256(bytes.fromhex(module["bytecode"].removeprefix("0x"))).hexdigest()
        if digest != manifest.get("module_bytecode_sha256"):
            raise ValueError("The module on devnet does not match the recorded deployment.")
        result = await chain.client.account_resource(owner.address(), f"{address}::game::Config")
        oracle = result["data"]["oracle_key"].removeprefix("0x")
        if oracle != owner.public_key().to_crypto_bytes().hex():
            raise ValueError("The configured referee key does not match this local deployer.")
    finally:
        await chain.close()


async def check(data: Path) -> None:
    manifest_path = ROOT / "deployment.json"
    if not manifest_path.is_file():
        raise ValueError("Local setup is incomplete: a verified deployment file and its deployer are required.")
    owner = load_operator(data)
    if not owner:
        raise ValueError("Local setup is incomplete: a verified deployment file and its deployer are required.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    await verify_deployment(manifest, owner)


if __name__ == "__main__":
    directory = Path(os.getenv("BLOCKWORD_DATA_DIR", str(ROOT / ".local")))
    try:
        asyncio.run(check(directory))
    except Exception as exc:
        print(f"Setup check failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("No deployment was attempted. See the README before choosing a new deployment.", file=sys.stderr)
        sys.exit(1)
    print("Local deployer, devnet module, and referee configuration match. No transactions were sent.")
