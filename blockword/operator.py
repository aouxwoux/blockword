import os
from pathlib import Path

from aptos_sdk.account import Account


def load_operator(directory):
    key = os.getenv("BLOCKWORD_OPERATOR_KEY")
    if key:
        try:
            return Account.load_key(key)
        except Exception:
            raise ValueError("BLOCKWORD_OPERATOR_KEY is not a valid Ed25519 private key.") from None
    path = Path(os.getenv("BLOCKWORD_DEPLOYER_FILE", str(directory / "deployer.json")))
    return Account.load(str(path)) if path.is_file() else None
