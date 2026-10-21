"""play a live round using public feedback, without reading the saved answer."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import uuid

import httpx
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from blockword.game import GLOSSARY, score


def play(base_url: str, output: Path, session_file: Path | None = None):
    with httpx.Client(base_url=base_url, timeout=90, trust_env=False,
                      headers={"Origin": base_url.rstrip("/")}) as api:
        if session_file and session_file.exists():
            for key, value in json.loads(session_file.read_text()).items():
                api.cookies.set(key, value)
        def post(path, payload):
            # reuse the request id after a dropped connection; keep the cookies for recovery.
            for attempt in range(3):
                try:
                    return api.post(path, json=payload).raise_for_status().json()
                except httpx.TransportError:
                    if attempt == 2 or (path == "/api/start" and not api.cookies.get("blockword_session")):
                        raise
                    print("Connection interrupted; retrying the same saved request.", flush=True)
                finally:
                    if session_file:
                        session_file.write_text(json.dumps(dict(api.cookies)))
                        session_file.chmod(0o600)
        for attempt in range(3):
            try:
                config = api.get("/api/config").raise_for_status().json()
                break
            except httpx.TransportError:
                if attempt == 2:
                    raise
        assert config["ready"], "Deploy and start the server first."
        state = post("/api/start", {})
        assert state["commitment"] and not state["answer"]
        candidates = list(GLOSSARY)
        while not state["finished"]:
            # choose the guess with the smallest worst-case bucket; break ties with a possible answer.
            def rank(word):
                buckets = Counter(tuple(score(answer, word)) for answer in candidates)
                return max(buckets.values()), word not in candidates, word
            word = min(GLOSSARY, key=rank)
            request_id = str(uuid.uuid4())
            state = post("/api/guess", {"word": word, "request_id": request_id})
            feedback = state["board"][-1]["feedback"]
            candidates = [answer for answer in candidates if score(answer, word) == feedback]
            print(f"Guess {len(state['board'])}: {word} -> {feedback}", flush=True)
            # replay the request to check that it does not consume another guess.
            replay = post("/api/guess", {"word": word, "request_id": request_id})
            assert len(replay["board"]) == len(state["board"])
        assert state["verified"] and state["won"]
        assert state["passport"]["wins"] == 1
        assert len(state["board"]) <= 6
        manifest = config["deployment"]
        with httpx.Client(base_url=manifest["node_url"], timeout=30) as node:
            for receipt in state["receipts"]:
                transaction = node.get(f"{manifest['node_url']}/transactions/by_hash/{receipt['hash']}")
                tx = transaction.raise_for_status().json()
                assert tx["success"] and tx["vm_status"] == "Executed successfully"
            game = node.get(f"{manifest['node_url']}/accounts/{state['player']}/resource/{manifest['module']}::Game").raise_for_status().json()["data"]
            assert game["verified"] and game["won"]
            assert bytes.fromhex(game["answer"][2:]).decode() == state["answer"]
        report = {
            "verified_at": datetime.now(timezone.utc).isoformat(), "network": "devnet",
            "module": manifest["module"], "player": state["player"],
            "round_id": state["round_id"], "attempts": len(state["board"]),
            "answer": state["answer"], "won": state["won"], "verified": state["verified"],
            "passport": state["passport"], "receipts": state["receipts"],
            "checks": ["HTTP game flow", "feedback-only solver", "idempotent guess retries",
                       "every receipt fetched from fullnode", "on-chain verified Game resource"],
        }
        output.write_text(json.dumps(report, indent=2) + "\n")
        print(f"Verified win in {report['attempts']} guesses. Evidence: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, default=ROOT / "verification.json")
    parser.add_argument("--session-file", type=Path, help="Private cookie file for a live test, kept outside source.")
    args = parser.parse_args()
    play(args.url, args.output, args.session_file)
