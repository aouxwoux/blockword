import hashlib
import re
from pathlib import Path

import pytest
from aptos_sdk.account import Account
from blockword.game import GLOSSARY, score
from blockword.proofs import commitment, message


@pytest.mark.parametrize("answer,guess,expected", [
    ("peers", "epoch", [1, 1, 0, 0, 0]),
    ("peers", "peers", [2, 2, 2, 2, 2]),
    ("aptos", "peers", [1, 0, 0, 0, 2]),
    ("state", "stake", [2, 2, 2, 0, 2]),
    ("token", "coins", [0, 2, 0, 1, 0]),
    ("aptos", "bytes", [0, 0, 2, 0, 2]),
])
def test_scoring(answer, guess, expected):
    assert score(answer, guess) == expected


def test_letter_conservation_for_every_vocabulary_pair():
    from collections import Counter
    for answer in GLOSSARY:
        for guess in GLOSSARY:
            marked = Counter(g for g, value in zip(guess, score(answer, guess)) if value)
            assert marked <= Counter(answer)


def test_python_and_move_have_the_same_vocabulary():
    source = (Path(__file__).resolve().parents[1] / "contract/sources/game.move").read_text()
    body = source.split("public fun words()", 1)[1].split("#[view]", 1)[0]
    assert set(re.findall(r'b"([a-z]+)"', body)) == set(GLOSSARY)
    assert all(len(word) == 5 and word.isascii() for word in GLOSSARY)


def test_commitment_and_permits_bind_identity_and_round():
    deployment, player, other = (str(Account.generate().address()) for _ in range(3))
    salt = bytes(range(32))
    original = commitment(deployment, player, 1, "peers", salt)
    variants = [commitment(other, player, 1, "peers", salt),
                commitment(deployment, other, 1, "peers", salt),
                commitment(deployment, player, 2, "peers", salt),
                commitment(deployment, player, 1, "aptos", salt),
                commitment(deployment, player, 1, "peers", bytes(reversed(salt)))]
    assert all(value != original for value in variants)
    assert len(original) == 32
    owner = Account.generate()
    permit = message("BLOCKWORD_START_V1", deployment, player, 1, original)
    signature = owner.sign(permit)
    assert owner.public_key().verify(permit, signature)
    wrong = message("BLOCKWORD_START_V1", deployment, player, 2, original)
    assert not owner.public_key().verify(wrong, signature)


def test_bcs_commitment_known_vector():
    # catch a switch from raw BCS bytes to JSON or hex text.
    domain = b"BLOCKWORD_ANSWER_V1"
    raw = (bytes([len(domain)]) + domain + bytes(31) + b"\x01" + bytes(31) + b"\x02"
           + (7).to_bytes(8, "little") + b"\x05peers\x20" + bytes(range(32)))
    assert commitment("0x1", "0x2", 7, "peers", bytes(range(32))) == hashlib.sha3_256(raw).digest()
