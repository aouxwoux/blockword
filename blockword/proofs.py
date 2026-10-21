"""keep the BCS field order in sync with the three permit/commitment structs in game.move."""
import hashlib
from aptos_sdk.account_address import AccountAddress
from aptos_sdk.bcs import Serializer


def message(domain: str, deployment: str, player: str, round_id: int,
            *fields: bytes | int) -> bytes:
    out = Serializer()
    out.to_bytes(domain.encode())
    AccountAddress.from_str(deployment).serialize(out)
    AccountAddress.from_str(player).serialize(out)
    out.u64(round_id)
    for field in fields:
        if isinstance(field, int):
            out.u64(field)
        else:
            out.to_bytes(field)
    return out.output()


def commitment(deployment: str, player: str, round_id: int, answer: str, salt: bytes) -> bytes:
    return hashlib.sha3_256(message("BLOCKWORD_ANSWER_V1", deployment, player,
                                  round_id, answer.encode(), salt)).digest()
