import asyncio
from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path
import secrets

from aptos_sdk.account import Account
from aptos_sdk.async_client import ApiError, FaucetClient, ResourceNotFound
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .chain import Chain, FAUCET
from .game import GLOSSARY, score
from .proofs import commitment, message
from .store import Store
from .accounts import Accounts, AccountError
from .account_api import router as account_router
from .hosting import public_origin, secure_cookie
from .operator import load_operator
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.getenv("BLOCKWORD_DATA_DIR", str(ROOT / ".local")))
COOKIE = "blockword_session"
log = logging.getLogger("blockword")


class MissingRoundBackup(Exception):
    """the saved answer is missing or belongs to a different round."""


def round_secret(state: dict, game: dict, deployment: str, player: str) -> dict:
    secret = state.get("secret")
    try:
        if not isinstance(secret, dict) or secret.get("round_id") != int(game["round_id"]):
            raise ValueError("Wrong round")
        salt = bytes.fromhex(secret["salt"])
        if len(salt) != 32 or secret["answer"] not in GLOSSARY:
            raise ValueError("Invalid answer data")
        expected = commitment(deployment, player, secret["round_id"], secret["answer"], salt)
        if "commitment" in game and expected.hex() != game["commitment"].removeprefix("0x"):
            raise ValueError("Wrong commitment")
    except (ValueError, TypeError, KeyError) as exc:
        raise MissingRoundBackup(
            "The saved answer for this round is missing or does not match. "
            "Restore the original local data directory or its backup before continuing."
        ) from exc
    return secret


class Service:
    def __init__(self):
        self.public_origin = public_origin()
        if os.getenv("VERCEL") and (not os.getenv("DATABASE_URL") or not self.public_origin):
            raise ValueError("Vercel requires DATABASE_URL and BLOCKWORD_PUBLIC_ORIGIN.")
        self.store = Store(DATA)
        self.accounts = Accounts(self.store)
        self.lock = self.store.game_lock()
        manifest = ROOT / "deployment.json"
        self.deployment = json.loads(manifest.read_text()) if manifest.exists() else {}
        self.owner = load_operator(DATA)
        self.chain = Chain(self.deployment["address"], max_gas_amount=20_000) if self.deployment else None
        self.ready = bool(self.owner and self.chain and
                          str(self.owner.address()) == self.deployment["address"])

    async def resource(self, player: Account, name: str) -> dict | None:
        try:
            result = await self.chain.client.account_resource(
                player.address(), f"{self.chain.address}::game::{name}")
            return result["data"]
        except ResourceNotFound:
            return None
        except ApiError as exc:
            if exc.status_code == 404:
                return None
            raise

    async def settle_pending(self, token: str, state: dict):
        for receipt in state["receipts"]:
            if receipt["status"] != "submitted":
                continue
            try:
                if "signed_bcs" in receipt:
                    try:
                        existing = await self.chain.client.transaction_by_hash(receipt["hash"])
                    except ApiError as exc:
                        if exc.status_code != 404:
                            raise
                        existing = None
                    if existing and existing.get("type") != "pending_transaction":
                        if not existing.get("success"):
                            receipt["status"] = "failed"
                            self.store.put(token, state)
                            raise RuntimeError("The transaction failed on Aptos.")
                        receipt.update(status="confirmed", version=existing["version"], gas_used=existing["gas_used"])
                        self.store.put(token, state)
                        continue
                    if not existing:
                        if "sender" in receipt and await self.chain.expired_uncommitted(receipt):
                            receipt["status"] = "expired"
                            self.store.put(token, state)
                            raise ValueError("The saved request expired without completing. You can retry your guess.")
                        # reuse the signed bytes so a lost response cannot turn a retry into another guess.
                        await self.chain.broadcast(receipt)
                tx = await self.chain.wait(receipt["hash"])
                receipt.update(status="confirmed", version=tx["version"], gas_used=tx["gas_used"])
                self.store.put(token, state)
            except Exception:
                if receipt["status"] == "expired":
                    raise
                # a timeout can still land on-chain; only retry a confirmed failure.
                try:
                    tx = await self.chain.client.transaction_by_hash(receipt["hash"])
                except Exception:
                    # keep unknown results in the journal until recovery can check them.
                    raise
                if tx.get("type") != "pending_transaction" and tx.get("success") is False:
                    receipt["status"] = "failed"
                    self.store.put(token, state)
                raise

    async def transact(self, token: str, state: dict, player: Account,
                       function: str, *args, request_id: str = ""):
        await self.ensure_funded(token, state, player)
        prepared = await self.chain.prepare(player, function, *args)
        state["receipts"].append({**prepared, "kind": function,
                                  "status": "submitted", "request_id": request_id})
        self.store.put(token, state)
        await self.settle_pending(token, state)

    async def ensure_funded(self, token: str, state: dict, player: Account):
        await self.settle_pending(token, state)
        try:
            balance = await self.chain.client.account_balance(player.address())
        except ApiError as exc:
            if exc.status_code != 404:
                raise
            balance = 0
        if balance < 3_000_000:
            if await self.chain.client.account_balance(self.owner.address()) < 10_000_000:
                await FaucetClient(FAUCET, self.chain.client).fund_account(self.owner.address(), 100_000_000)
            prepared = await self.chain.prepare_funding(self.owner, player)
            state["receipts"].append({**prepared, "kind": "fund", "status": "submitted"})
            self.store.put(token, state)
            await self.settle_pending(token, state)
        state["funded"] = True
        self.store.put(token, state)

    async def sync(self, token: str, state: dict, recover: bool = True) -> tuple[dict | None, dict | None]:
        if recover:
            await self.settle_pending(token, state)
        player = Account.load_key(state["key"])
        game = await self.resource(player, "Game")
        passport = await self.resource(player, "Passport")
        # the app may have stopped after finishing the round but before revealing it.
        if recover and game and game["finished"] and not game["verified"]:
            secret = round_secret(state, game, self.chain.address, str(player.address()))
            await self.transact(token, state, player, "reveal", secret["answer"].encode(),
                                bytes.fromhex(secret["salt"]))
            game = await self.resource(player, "Game")
            passport = await self.resource(player, "Passport")
        if recover and game and game["verified"]:
            self.accounts.save_round(token,self.deployment,self.public(state,game,passport))
        return game, passport

    def public(self, state: dict, game: dict | None, passport: dict | None) -> dict:
        player = Account.load_key(state["key"])
        board = []
        if game:
            board = [{"word": bytes.fromhex(w[2:]).decode(), "feedback": list(bytes.fromhex(f[2:]))}
                     for w, f in zip(game["guesses"], game["feedback"])]
        answer = bytes.fromhex(game["answer"][2:]).decode() if game and game["verified"] else None
        return {
            "player": str(player.address()), "round_id": int(game["round_id"]) if game else 0,
            "board": board, "finished": bool(game and game["finished"]),
            "verified": bool(game and game["verified"]), "won": bool(game and game["won"]),
            "answer": answer, "definition": GLOSSARY.get(answer),
            "commitment": game["commitment"] if game else None,
            "passport": {k: int(v) for k, v in (passport or {}).items()},
            "receipts": [{k: v for k, v in r.items()
                          if k in {"kind", "hash", "status", "version", "gas_used"}}
                         for r in state["receipts"]],
        }


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.service = Service()
    svc = app.state.service
    try:
        if os.getenv("VERCEL"):
            if not svc.ready:
                raise ValueError("Set the matching BLOCKWORD_OPERATOR_KEY before deployment.")
            from scripts.check_deployment import verify_deployment
            await verify_deployment(svc.deployment, svc.owner)
        yield
    finally:
        if svc.chain:
            await svc.chain.close()
        await svc.accounts.close()


app = FastAPI(title="Blockword", lifespan=lifespan)
app.include_router(account_router)


@app.exception_handler(AccountError)
async def account_error(request: Request, exc: AccountError):
    return JSONResponse({"detail":exc.detail},status_code=exc.status)


@app.middleware("http")
async def local_boundary(request: Request, call_next):
    configured = request.app.state.service.public_origin
    host = request.headers.get("host", "").lower()
    # hosts may probe with an internal Host header; this route exposes no player data.
    health_probe = request.url.path == "/healthz" and request.method in {"GET", "HEAD"}
    allowed = (host == urlsplit(configured).netloc.lower()) if configured else (
        request.url.hostname in {"127.0.0.1", "localhost", "testserver"})
    if not allowed and not health_probe:
        return JSONResponse({"detail": "This application address is not enabled."}, status_code=403)
    request.state.public_origin = configured or str(request.base_url).rstrip("/")
    origin = request.headers.get("origin")
    if request.method not in {"GET","HEAD","OPTIONS"} and (
        (origin and origin.rstrip("/") != request.state.public_origin) or
        request.headers.get("sec-fetch-site") == "cross-site"
    ):
        return JSONResponse({"detail": "Cross-site requests are disabled."}, status_code=403)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; "
        "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )
    if getattr(request.state, "new_session", None):
        response.set_cookie(COOKIE, request.state.new_session, httponly=True,
                            samesite="strict", secure=secure_cookie(request), max_age=30 * 86400)
    return response


def service(request: Request) -> Service:
    result = request.app.state.service
    if not result.ready:
        raise HTTPException(503, "Run python scripts/deploy.py first, using the same BLOCKWORD_DATA_DIR.")
    return result


def session(request: Request, svc: Service) -> tuple[str, dict]:
    token = request.cookies.get(COOKIE, "")
    state = svc.store.get(token) if token else None
    if not state:
        raise HTTPException(401, "Start a round to create a demo wallet.")
    return token, state


def chain_failure(exc: Exception):
    log.warning("Chain request failed (%s).", type(exc).__name__)
    if isinstance(exc, MissingRoundBackup):
        raise HTTPException(409, str(exc)) from exc
    if isinstance(exc, ApiError):
        log.warning("Fullnode status %s: %s", exc.status_code, str(exc)[:400])
    if isinstance(exc, ValueError):
        raise HTTPException(400, str(exc)) from exc
    raise HTTPException(503, "Aptos has not confirmed this request. Choose Check & finish verification "
                        "before trying again. Your saved request will be checked first.") from exc


@app.get("/")
async def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.api_route("/healthz", methods=["GET", "HEAD"])
async def health():
    # this checks the process; startup checks the deployment separately.
    return {"status": "ok"}


@app.get("/api/config")
async def config(request: Request):
    svc = request.app.state.service
    return {"ready": svc.ready, "deployment": svc.deployment,
            "words": sorted(GLOSSARY), "wallet_mode": "local custodial demo"}


@app.get("/api/state")
async def get_state(request: Request):
    svc = service(request)
    token, state = session(request, svc)
    async with svc.lock:
        try:
            state = svc.store.get(token)
            game, passport = await svc.sync(token, state, recover=False)
            return svc.public(state, game, passport)
        except Exception as exc:
            chain_failure(exc)


@app.post("/api/start")
async def start(request: Request):
    svc = service(request)
    async with svc.lock:
        token = request.cookies.get(COOKIE, "")
        state = svc.store.get(token) if token else None
        if not state:
            if svc.store.count() >= 12:
                raise HTTPException(429, "This demo has reached its 12-wallet funding limit.")
            token = secrets.token_urlsafe(32)
            player = Account.generate()
            state = {"key": str(player.private_key), "receipts": [], "secret": None, "funded": False}
            svc.store.put(token, state)
            request.state.new_session = token
        player = Account.load_key(state["key"])
        try:
            await svc.ensure_funded(token, state, player)
            game, passport = await svc.sync(token, state)
            if game and not game["verified"]:
                return svc.public(state, game, passport)
            round_id = int(passport["rounds"]) + 1 if passport else 1
            if round_id > 20:
                raise ValueError("This wallet has reached the 20-round demo limit.")
            # keep the same answer if submitting the commitment fails.
            if not state["secret"] or state["secret"]["round_id"] != round_id:
                answer = secrets.choice(list(GLOSSARY))
                salt = secrets.token_bytes(32)
                state["secret"] = {"round_id": round_id, "answer": answer, "salt": salt.hex()}
                svc.store.put(token, state)
            secret = state["secret"]
            digest = commitment(svc.chain.address, str(player.address()), round_id,
                                secret["answer"], bytes.fromhex(secret["salt"]))
            permit = message("BLOCKWORD_START_V1", svc.chain.address, str(player.address()), round_id, digest)
            await svc.transact(token, state, player, "start", round_id, digest, svc.owner.sign(permit).data())
            game, passport = await svc.sync(token, state)
            return svc.public(state, game, passport)
        except Exception as exc:
            chain_failure(exc)


class Guess(BaseModel):
    word: str = Field(min_length=5, max_length=5, pattern="^[a-zA-Z]{5}$")
    request_id: str = Field(min_length=16, max_length=64, pattern="^[a-zA-Z0-9-]+$")
    expected_round: int | None = Field(default=None, ge=1)
    expected_attempt: int | None = Field(default=None, ge=1, le=6)


@app.post("/api/guess")
async def guess(payload: Guess, request: Request):
    svc = service(request)
    token, state = session(request, svc)
    async with svc.lock:
        # another tab may have submitted a guess while this request waited for the lock.
        state = svc.store.get(token)
        try:
            game, passport = await svc.sync(token, state)
            if any(r.get("request_id") == payload.request_id and r["status"] == "confirmed"
                   for r in state["receipts"]):
                return svc.public(state, game, passport)
            if not game or game["finished"]:
                raise ValueError("Start a new round first.")
            if ((payload.expected_round is not None and payload.expected_round != int(game["round_id"])) or
                (payload.expected_attempt is not None and payload.expected_attempt != len(game["guesses"]) + 1)):
                raise ValueError("Your board has changed. Check the round before submitting another guess.")
            word = payload.word.lower()
            if word not in GLOSSARY:
                raise ValueError("Pick a five-letter term from the word list.")
            player = Account.load_key(state["key"])
            secret = round_secret(state, game, svc.chain.address, str(player.address()))
            feedback = bytes(score(secret["answer"], word))
            permit = message("BLOCKWORD_GUESS_V1", svc.chain.address, str(player.address()),
                             int(game["round_id"]), len(game["guesses"]) + 1, word.encode(), feedback)
            await svc.transact(token, state, player, "guess", word.encode(), feedback,
                               svc.owner.sign(permit).data(), request_id=payload.request_id)
            game, passport = await svc.sync(token, state)
            return svc.public(state, game, passport)
        except Exception as exc:
            chain_failure(exc)


@app.post("/api/forfeit")
async def forfeit(request: Request):
    svc = service(request)
    token, _ = session(request, svc)
    async with svc.lock:
        state = svc.store.get(token)
        try:
            game, passport = await svc.sync(token, state)
            if game and not game["finished"]:
                await svc.transact(token, state, Account.load_key(state["key"]), "forfeit")
                game, passport = await svc.sync(token, state)
            return svc.public(state, game, passport)
        except Exception as exc:
            chain_failure(exc)


@app.post("/api/recover")
async def recover(request: Request):
    svc = service(request)
    token, _ = session(request, svc)
    async with svc.lock:
        state = svc.store.get(token)
        try:
            game, passport = await svc.sync(token, state)
            return svc.public(state, game, passport)
        except Exception as exc:
            chain_failure(exc)


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
