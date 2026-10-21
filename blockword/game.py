from collections import Counter

GLOSSARY = {
    "aptos": "The layer-one network this game runs on. Its contracts are written in Move.",
    "asset": "Something represented on-chain, from a coin to a collectible or an ownership right.",
    "block": "A batch of transactions accepted into a blockchain's history.",
    "bytes": "Units of digital data. A byte holds eight bits; addresses and hashes are made of bytes.",
    "chain": "A shared history that participants can independently verify.",
    "coins": "Fungible units of value. APT pays for execution and storage on Aptos.",
    "dapps": "Applications that use smart contracts for part of their behavior.",
    "epoch": "A period in which a network operates with a particular validator configuration.",
    "layer": "A level in a blockchain system. Aptos is a layer-one network.",
    "miner": "A participant that proposes blocks in proof-of-work networks. Aptos uses validators instead.",
    "nodes": "Computers that take part in the network or serve its data.",
    "nonce": "A value used once. Transaction ordering and replay protection rely on related ideas.",
    "peers": "Other computers a node communicates with in a distributed network.",
    "proof": "Evidence that lets another party check a claim.",
    "relay": "To pass a message or transaction to another participant.",
    "shard": "A partition of a larger dataset or system. This game does not require sharding.",
    "stake": "Tokens committed to help secure a proof-of-stake network.",
    "state": "The current values stored by accounts and contracts.",
    "swaps": "Exchanges of one asset for another, often through a decentralized exchange.",
    "token": "A digital unit recorded and managed by a contract.",
    "trust": "An assumption about who or what must behave correctly. This game makes its assumptions visible.",
    "vault": "A place or contract used to hold assets under defined rules.",
}


def score(answer: str, guess: str) -> list[int]:
    """0 = absent, 1 = elsewhere, 2 = exact; consume exact matches first."""
    if len(answer) != 5 or len(guess) != 5:
        raise ValueError("Both words must have five letters.")
    result = [2 if a == g else 0 for a, g in zip(answer, guess)]
    remaining = Counter(a for i, a in enumerate(answer) if result[i] != 2)
    for i, letter in enumerate(guess):
        if result[i] == 0 and remaining[letter]:
            result[i] = 1
            remaining[letter] -= 1
    return result
