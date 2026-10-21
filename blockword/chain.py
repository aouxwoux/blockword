import hashlib
import json
from aptos_sdk.account import Account
from aptos_sdk.account_address import AccountAddress
from aptos_sdk.async_client import ClientConfig, RestClient
from aptos_sdk.bcs import Deserializer, Serializer
from aptos_sdk.transactions import EntryFunction, SignedTransaction, TransactionArgument, TransactionPayload

NODE = "https://fullnode.devnet.aptoslabs.com/v1"
FAUCET = "https://faucet.devnet.aptoslabs.com"


class Chain:
    def __init__(self, address: str, node: str = NODE, max_gas_amount: int = 100_000):
        self.address = address
        self.client = RestClient(node, ClientConfig(max_gas_amount=max_gas_amount))

    async def prepare(self, account: Account, function: str, *args: bytes | int) -> dict:
        arguments = [TransactionArgument(arg, Serializer.u64 if isinstance(arg, int)
                                        else Serializer.to_bytes) for arg in args]
        payload = TransactionPayload(EntryFunction.natural(
            f"{self.address}::game", function, [], arguments))
        return await self.prepare_payload(account, payload)

    async def prepare_payload(self, account: Account, payload: TransactionPayload) -> dict:
        signed = await self.client.create_bcs_signed_transaction(account, payload)
        raw = signed.bytes()
        return {"hash": self.transaction_hash(raw), "signed_bcs": raw.hex(),
                "expires_at": signed.transaction.expiration_timestamps_secs,
                "sender": str(signed.transaction.sender), "sequence": signed.transaction.sequence_number}

    async def expired_uncommitted(self, prepared: dict) -> bool:
        """check ledger time and sequence before treating a transaction as expired."""
        ledger = await self.client.info()
        if int(ledger["ledger_timestamp"]) // 1_000_000 <= prepared["expires_at"]:
            return False
        sender = AccountAddress.from_str(prepared["sender"])
        sequence = await self.client.account_sequence_number(sender)
        if sequence <= prepared["sequence"]:
            return True
        history = await self.client.transactions_by_account(sender, start=prepared["sequence"], limit=1)
        if history and int(history[0]["sequence_number"]) == prepared["sequence"]:
            return history[0]["hash"] != prepared["hash"]
        raise RuntimeError("The saved request outcome is unavailable. Keep its local receipt for inspection.")

    @staticmethod
    def transaction_hash(raw: bytes) -> str:
        # hash = domain prefix + enum tag 0 + signed BCS bytes.
        # see SignedTransaction.Hash in aptos-labs/aptos-go-sdk (signedTransaction.go).
        prefix = hashlib.sha3_256(b"APTOS::Transaction").digest()
        return "0x" + hashlib.sha3_256(prefix + b"\x00" + raw).hexdigest()

    async def broadcast(self, prepared: dict) -> str:
        raw = bytes.fromhex(prepared["signed_bcs"])
        if self.transaction_hash(raw) != prepared["hash"]:
            raise ValueError("The saved transaction does not match its receipt.")
        signed = SignedTransaction.deserialize(Deserializer(raw))
        result = await self.client.submit_bcs_transaction(signed)
        if result != prepared["hash"]:
            raise RuntimeError("Aptos returned a different transaction hash.")
        return result

    async def call(self, account: Account, function: str, *args: bytes | int) -> str:
        return await self.broadcast(await self.prepare(account, function, *args))

    async def prepare_funding(self, owner: Account, player: Account) -> dict:
        payload = TransactionPayload(EntryFunction.natural("0x1::aptos_account", "transfer", [], [
            TransactionArgument(player.address(), Serializer.struct),
            TransactionArgument(5_000_000, Serializer.u64),
        ]))
        return await self.prepare_payload(owner, payload)

    async def wait(self, tx: str) -> dict:
        await self.client.wait_for_transaction(tx)
        result = await self.client.transaction_by_hash(tx)
        if not result.get("success"):
            raise RuntimeError(result.get("vm_status", "Transaction failed"))
        return result

    async def view(self, function: str, player: str) -> dict:
        result = await self.client.view(f"{self.address}::game::{function}", [], [player])
        return json.loads(result)[0]

    async def fund_player(self, owner: Account, player: Account) -> str:
        tx = await self.client.bcs_transfer(owner, player.address(), 5_000_000)
        await self.wait(tx)
        return tx

    async def close(self):
        await self.client.close()
