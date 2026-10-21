import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aptos_sdk.account import Account
from aptos_sdk.account_address import AccountAddress
from aptos_sdk.authenticator import Authenticator, Ed25519Authenticator
from aptos_sdk.bcs import Serializer
from aptos_sdk.ed25519 import PublicKey, Signature
from aptos_sdk.transactions import EntryFunction, RawTransaction, SignedTransaction, TransactionArgument, TransactionPayload

from blockword.chain import Chain


def recorded_transaction():
    # public transaction from the devnet run, used as a hash fixture.
    record = json.loads((Path(__file__).parent / "fixtures/aptos-guess-transaction.json").read_text())
    module, function = record["payload"]["function"].rsplit("::", 1)
    args = [TransactionArgument(bytes.fromhex(value[2:]), Serializer.to_bytes)
            for value in record["payload"]["arguments"]]
    payload = TransactionPayload(EntryFunction.natural(module, function, [], args))
    raw = RawTransaction(AccountAddress.from_str(record["sender"]), int(record["sequence_number"]),
                         payload, int(record["max_gas_amount"]), int(record["gas_unit_price"]),
                         int(record["expiration_timestamp_secs"]), record["chain_id"])
    signature = record["signature"]
    signed = SignedTransaction(raw, Authenticator(Ed25519Authenticator(
        PublicKey.from_str(signature["public_key"]), Signature.from_str(signature["signature"]))))
    return record, signed


def test_local_hash_matches_a_recorded_executed_aptos_transaction():
    record, signed = recorded_transaction()
    assert signed.verify()
    assert Chain.transaction_hash(signed.bytes()) == record["hash"]


def test_prepared_bytes_can_be_rebroadcast_without_resigning():
    record, signed = recorded_transaction()
    async def run():
        chain = Chain("0x1")
        try:
            chain.client.create_bcs_signed_transaction = AsyncMock(return_value=signed)
            chain.client.submit_bcs_transaction = AsyncMock(return_value=record["hash"])
            prepared = await chain.prepare(Account.generate(), "guess", b"asset")
            assert prepared["hash"] == record["hash"]
            assert prepared["sequence"] == int(record["sequence_number"])
            assert prepared["expires_at"] == int(record["expiration_timestamp_secs"])
            assert await chain.broadcast(prepared) == record["hash"]
            assert await chain.broadcast(prepared) == record["hash"]
            sent = chain.client.submit_bcs_transaction.await_args_list
            assert sent[0].args[0].bytes() == sent[1].args[0].bytes() == signed.bytes()
            chain.client.create_bcs_signed_transaction.assert_awaited_once()
        finally:
            await chain.close()
    asyncio.run(run())


def test_journal_hash_mismatch_is_rejected_before_submission():
    async def run():
        chain = Chain("0x1")
        try:
            chain.client.submit_bcs_transaction = AsyncMock()
            with pytest.raises(ValueError, match="does not match"):
                await chain.broadcast({"hash": "0xwrong", "signed_bcs": "00"})
            chain.client.submit_bcs_transaction.assert_not_awaited()
        finally:
            await chain.close()
    asyncio.run(run())


@pytest.mark.parametrize("ledger_time,sequence,expected", [(99, 3, False), (101, 3, True)])
def test_expiry_requires_ledger_time_and_an_unconsumed_account_sequence(ledger_time, sequence, expected):
    async def run():
        chain = Chain("0x1")
        try:
            chain.client.info = AsyncMock(return_value={"ledger_timestamp": str(ledger_time * 1_000_000)})
            chain.client.account_sequence_number = AsyncMock(return_value=sequence)
            prepared = {"expires_at": 100, "sender": "0x1", "sequence": 3, "hash": "0xabc"}
            assert await chain.expired_uncommitted(prepared) is expected
        finally:
            await chain.close()
    asyncio.run(run())


def test_an_unknown_consumed_sequence_is_never_treated_as_safe_to_retry():
    async def run():
        chain = Chain("0x1")
        try:
            chain.client.info = AsyncMock(return_value={"ledger_timestamp": "101000000"})
            chain.client.account_sequence_number = AsyncMock(return_value=4)
            chain.client.transactions_by_account = AsyncMock(return_value=[])
            with pytest.raises(RuntimeError, match="outcome is unavailable"):
                await chain.expired_uncommitted({"expires_at":100,"sender":"0x1","sequence":3,"hash":"0xabc"})
        finally:
            await chain.close()
    asyncio.run(run())
