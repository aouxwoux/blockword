import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from aptos_sdk.account import Account
from aptos_sdk.async_client import FaucetClient, ResourceNotFound
from aptos_sdk.package_publisher import PackagePublisher
from blockword.chain import Chain, NODE, FAUCET


async def deploy(cli: str, skip_tests: bool = False):
    data = Path(os.getenv("BLOCKWORD_DATA_DIR", str(ROOT / ".local")))
    data.mkdir(parents=True, exist_ok=True)
    key_file = data / "deployer.json"
    if key_file.exists():
        account = Account.load(str(key_file))
    else:
        account = Account.generate()
        account.store(str(key_file))
        try:
            key_file.chmod(0o600)
        except OSError:
            pass
    address = str(account.address())
    print(f"Deployer: {address}", flush=True)
    chain = Chain(address)
    try:
        try:
            balance = await chain.client.account_balance(account.address())
        except Exception:
            balance = 0
        if balance < 20_000_000:
            print("Requesting free devnet APT...", flush=True)
            await FaucetClient(FAUCET, chain.client).fund_account(address, 100_000_000)
        if not skip_tests:
            subprocess.run([cli, "move", "test", "--package-dir", str(ROOT / "contract"),
                            "--named-addresses", f"blockword={address}"], check=True)
        subprocess.run([cli, "move", "compile", "--package-dir", str(ROOT / "contract"),
                        "--named-addresses", f"blockword={address}",
                        "--included-artifacts", "all", "--save-metadata"], check=True)
        output = ROOT / "deployment.json"
        previous = json.loads(output.read_text()) if output.exists() else {}
        # reuse the module if it is still there; immutable packages cannot be upgraded.
        try:
            await chain.client.account_module(account.address(), "game")
            publish_tx = previous.get("publish_transaction") if previous.get("address") == address else None
            if not publish_tx:
                history = await chain.client.transactions_by_account(account.address(), limit=100)
                publish_tx = next((tx["hash"] for tx in history
                                   if tx.get("success") and tx.get("payload", {}).get("function") ==
                                   "0x1::code::publish_package_txn"), None)
        except Exception as exc:
            from aptos_sdk.async_client import ApiError
            if not isinstance(exc, ApiError) or exc.status_code != 404:
                raise
            print("Publishing immutable Move package...", flush=True)
            hashes = await PackagePublisher(chain.client).publish_package_in_path(
                account, str(ROOT / "contract"))
            for tx in hashes:
                await chain.wait(tx)
            publish_tx = hashes[-1]
        try:
            await chain.client.account_resource(account.address(), f"{address}::game::Config")
            config_tx = previous.get("configure_transaction") if previous.get("address") == address else None
        except ResourceNotFound:
            config_tx = await chain.call(account, "configure", account.public_key().to_crypto_bytes())
            await chain.wait(config_tx)
        ledger = await chain.client.info()
        module = await chain.client.account_module(account.address(), "game")
        bytecode = bytes.fromhex(module["bytecode"][2:])
        compiled = (ROOT / "contract/build/Blockword/bytecode_modules/game.mv").read_bytes()
        if compiled != bytecode:
            raise RuntimeError("Published bytecode does not match this source build. Use a new deployer for changed immutable code.")
        manifest = {
            "network": "devnet", "chain_id": ledger["chain_id"], "address": address,
            "module": f"{address}::game", "node_url": NODE,
            "publish_transaction": publish_tx, "configure_transaction": config_tx,
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "module_bytecode_sha256": hashlib.sha256(bytecode).hexdigest(),
            "explorer": f"https://explorer.aptoslabs.com/account/{address}/modules?network=devnet",
        }
        output.write_text(json.dumps(manifest, indent=2) + "\n")
        readme = ROOT / "README.md"
        if readme.exists():
            details = (
                f"<!-- deployment:start -->\n"
                f"**network:** Aptos devnet (chain ID {manifest['chain_id']})  \n"
                f"**module:** `{manifest['module']}`  \n"
                f"**contract address:** `{address}`  \n"
                f"**verified:** {manifest['verified_at']}\n\n"
                f"[view the contract]({manifest['explorer']})\n\n"
                f"- publish transaction: `{publish_tx}`\n"
                f"- referee configuration: `{config_tx}`\n\n"
                f"the deployment script read the address and bytecode back from the fullnode. "
                f"receipts are in `deployment.json`.\n"
                f"<!-- deployment:end -->"
            )
            readme.write_text(re.sub(r"<!-- deployment:start -->.*?<!-- deployment:end -->",
                                     lambda _: details, readme.read_text(encoding="utf-8"), flags=re.S),
                              encoding="utf-8")
        print(f"Verified module: {manifest['module']}", flush=True)
        print(f"Deployment receipt: {output}", flush=True)
    finally:
        await chain.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--aptos", default=shutil.which("aptos"))
    parser.add_argument("--skip-tests", action="store_true",
                        help="Skip only when this exact source and address have already passed Move tests.")
    args = parser.parse_args()
    if not args.aptos:
        parser.error("Install the Aptos CLI or pass --aptos PATH_TO_APTOS.")
    asyncio.run(deploy(args.aptos, args.skip_tests))
