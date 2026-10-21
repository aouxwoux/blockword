import asyncio
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_deployment import check
from blockword.hosting import public_origin
import uvicorn


if __name__ == "__main__":
    if not public_origin():
        raise SystemExit("Set BLOCKWORD_PUBLIC_ORIGIN to the public HTTPS address before hosting.")
    asyncio.run(check(Path(os.getenv("BLOCKWORD_DATA_DIR", str(ROOT / ".local")))))
    uvicorn.run("blockword.app:app", host="0.0.0.0", port=int(os.getenv("PORT", "10000")),
                workers=1, proxy_headers=False)
