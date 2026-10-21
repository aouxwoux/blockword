import hashlib
import json
import secrets
import sqlite3
import time
import uuid
from urllib.parse import urlsplit

from aptos_sdk.account_address import AccountAddress
from aptos_sdk.async_client import ApiError, RestClient
from aptos_sdk.ed25519 import PublicKey, Signature

from .chain import NODE

AUTH_COOKIE = "blockword_player"
CHALLENGE_COOKIE = "blockword_login"
CHALLENGE_TTL = 300
SESSION_TTL = 86400


class AccountError(Exception):
    def __init__(self, status: int, detail: str):
        self.status, self.detail = status, detail
        super().__init__(detail)


def address(value: str) -> str:
    try:
        return str(AccountAddress.from_str_relaxed(value))
    except Exception as exc:
        raise AccountError(422, "Enter a valid Aptos wallet address.") from exc


class Accounts:
    def __init__(self, store, client=None, clock=time.time):
        self.store = store
        self.client = client or RestClient(NODE)
        self.clock = clock
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS players (
                    id TEXT PRIMARY KEY, wallet_address TEXT NOT NULL UNIQUE,
                    public_key TEXT NOT NULL, display_name TEXT NOT NULL,
                    created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS login_challenges (
                    id TEXT PRIMARY KEY, binding_hash TEXT NOT NULL, wallet_address TEXT NOT NULL,
                    message TEXT NOT NULL, nonce TEXT NOT NULL, origin TEXT NOT NULL,
                    chain_id INTEGER NOT NULL, created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL, consumed_at INTEGER, attempts INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS player_sessions (
                    id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE,
                    player_id TEXT NOT NULL REFERENCES players(id),
                    created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
                    revoked_at INTEGER, user_agent TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS player_session_owner ON player_sessions(player_id);
                CREATE TABLE IF NOT EXISTS account_rate_limits (
                    bucket TEXT PRIMARY KEY, count INTEGER NOT NULL, expires_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS player_demo_links (
                    demo_id TEXT PRIMARY KEY REFERENCES sessions(id),
                    player_id TEXT NOT NULL REFERENCES players(id), linked_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS saved_rounds (
                    id TEXT PRIMARY KEY, demo_id TEXT NOT NULL REFERENCES sessions(id),
                    deployment TEXT NOT NULL, chain_id INTEGER NOT NULL, round_id INTEGER NOT NULL,
                    completed_at INTEGER NOT NULL, body TEXT NOT NULL,
                    UNIQUE(demo_id, deployment, chain_id, round_id)
                );
                CREATE INDEX IF NOT EXISTS saved_round_owner ON saved_rounds(demo_id, completed_at);
            """)

    async def close(self):
        await self.client.close()

    def throttle(self, scope: str, actor: str, limit: int):
        now = int(self.clock())
        bucket = self.store.digest(f"{scope}:{actor}:{now // 60}")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM account_rate_limits WHERE expires_at < ?", (now,))
            db.execute("INSERT INTO account_rate_limits VALUES (?, 1, ?) "
                       "ON CONFLICT(bucket) DO UPDATE SET count=account_rate_limits.count+1", (bucket, now + 120))
            count = db.execute("SELECT count FROM account_rate_limits WHERE bucket=?", (bucket,)).fetchone()[0]
        if count > limit:
            raise AccountError(429, "Too many sign-in requests. Wait a minute and try again.")

    async def challenge(self, wallet_address: str, origin: str, actor: str) -> tuple[dict, str]:
        self.throttle("challenge", actor, 10)
        wallet_address = address(wallet_address)
        if urlsplit(origin).scheme not in {"http", "https"} or "\n" in origin:
            raise AccountError(422, "The application address is invalid.")
        try:
            chain_id = int((await self.client.info())["chain_id"])
        except Exception as exc:
            raise AccountError(503, "Aptos devnet could not be checked. Try signing in again shortly.") from exc
        now, nonce, binding = int(self.clock()), secrets.token_hex(24), secrets.token_urlsafe(32)
        expires = now + CHALLENGE_TTL
        message = (f"Blockword sign-in\nApplication: {origin}\nWallet: {wallet_address}\n"
                   f"Network: Aptos devnet\nChain ID: {chain_id}\nChallenge: {nonce}\n"
                   f"Issued at: {now}\nExpires at: {expires}\n"
                   "This signs you in. It does not authorize any transactions.")
        identifier = str(uuid.uuid4())
        with self.store.connect() as db:
            db.execute("DELETE FROM login_challenges WHERE expires_at < ?", (now - 3600,))
            db.execute("INSERT INTO login_challenges "
                       "(id,binding_hash,wallet_address,message,nonce,origin,chain_id,created_at,expires_at) "
                       "VALUES (?,?,?,?,?,?,?,?,?)",
                       (identifier,self.store.digest(binding),wallet_address,message,nonce,origin,chain_id,now,expires))
        return {"challenge_id":identifier,"wallet_address":wallet_address,"network":"devnet",
                "chain_id":chain_id,"message":message,"nonce":nonce,"expires_at":expires,
                "sign_message":{"message":message,"nonce":nonce,"address":False,"application":False,"chainId":False}}, binding

    def _challenge(self, identifier: str, binding: str, origin: str) -> dict:
        with self.store.connect() as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM login_challenges WHERE id=?", (identifier,)).fetchone()
        if not row or not binding or row["binding_hash"] != self.store.digest(binding):
            raise AccountError(401, "This sign-in request belongs to another browser session. Start again.")
        if row["origin"] != origin:
            raise AccountError(401, "This sign-in request belongs to a different application address.")
        if row["consumed_at"] is not None or row["expires_at"] <= int(self.clock()) or row["attempts"] >= 5:
            raise AccountError(401, "This sign-in request has expired or was already used. Start again.")
        return dict(row)

    async def verify(self, payload: dict, binding: str, origin: str, actor: str,
                     user_agent: str, previous_token: str = "") -> tuple[dict, str, int]:
        self.throttle("verify", actor, 20)
        challenge = self._challenge(payload["challenge_id"], binding, origin)
        # wallets use two field orders; accept either, but match the full challenge byte for byte.
        expected = {f"APTOS\nnonce: {challenge['nonce']}\nmessage: {challenge['message']}",
                    f"APTOS\nmessage: {challenge['message']}\nnonce: {challenge['nonce']}"}
        try:
            key = PublicKey.from_str(payload["public_key"])
            signature = Signature.from_str(payload["signature"])
            valid = payload["full_message"] in expected and key.verify(payload["full_message"].encode(), signature)
        except Exception:
            valid = False
        if not valid:
            with self.store.connect() as db:
                db.execute("UPDATE login_challenges SET attempts=attempts+1 WHERE id=?", (challenge["id"],))
            raise AccountError(401, "The wallet signature did not match this sign-in request.")
        try:
            ledger = await self.client.info()
            if int(ledger["chain_id"]) != challenge["chain_id"]:
                raise AccountError(401, "Devnet changed while you were signing in. Start again.")
            try:
                current = await self.client.account(AccountAddress.from_str(challenge["wallet_address"]))
                auth_key = address(current["authentication_key"])
            except ApiError as exc:
                if exc.status_code != 404:
                    raise
                auth_key = challenge["wallet_address"]
        except AccountError:
            raise
        except Exception as exc:
            raise AccountError(503, "The wallet's current key could not be checked on devnet. Try again shortly.") from exc
        if str(AccountAddress.from_key(key)) != auth_key:
            raise AccountError(401, "This public key is not the wallet's current Ed25519 key on devnet.")
        now, token, session_id = int(self.clock()), secrets.token_urlsafe(32), str(uuid.uuid4())
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            consumed = db.execute("UPDATE login_challenges SET consumed_at=? WHERE id=? AND consumed_at IS NULL "
                                  "AND expires_at>? AND attempts<5", (now,challenge["id"],now))
            if consumed.rowcount != 1:
                raise AccountError(401, "This sign-in request has expired or was already used. Start again.")
            player = db.execute("SELECT id,public_key FROM players WHERE wallet_address=?", (challenge["wallet_address"],)).fetchone()
            player_id = player[0] if player else str(uuid.uuid4())
            if player and player[1] != str(key):
                # a login with the rotated key revokes sessions made with the old one.
                db.execute("UPDATE player_sessions SET revoked_at=? WHERE player_id=? AND revoked_at IS NULL", (now,player_id))
            db.execute("INSERT INTO players VALUES (?,?,?,?,?,?) ON CONFLICT(wallet_address) "
                       "DO UPDATE SET public_key=excluded.public_key,updated_at=excluded.updated_at",
                       (player_id,challenge["wallet_address"],str(key),
                        f"Player {challenge['wallet_address'][-6:]}",now,now))
            if previous_token:
                db.execute("UPDATE player_sessions SET revoked_at=? WHERE token_hash=?", (now,self.store.digest(previous_token)))
            db.execute("INSERT INTO player_sessions VALUES (?,?,?,?,?,?,?)",
                       (session_id,self.store.digest(token),player_id,now,now+SESSION_TTL,None,user_agent[:256]))
        return self.me(token), token, now + SESSION_TTL

    def identity(self, token: str) -> dict:
        if not token:
            raise AccountError(401, "Sign in with your wallet to open your player account.")
        with self.store.connect() as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT p.id,p.wallet_address,p.display_name,p.created_at,p.updated_at,"
                             "s.id AS session_id,s.expires_at FROM player_sessions s JOIN players p ON p.id=s.player_id "
                             "WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at>?",
                             (self.store.digest(token),int(self.clock()))).fetchone()
        if not row:
            raise AccountError(401, "Your player session has ended. Sign in again.")
        return dict(row)

    def me(self, token: str) -> dict:
        result = self.identity(token)
        with self.store.connect() as db:
            result["linked_demo_accounts"] = db.execute("SELECT count(*) FROM player_demo_links WHERE player_id=?", (result["id"],)).fetchone()[0]
        result["network"], result["game_signing"] = "devnet", "separate server-held demo wallet"
        return result

    def rename(self, token: str, name: str) -> dict:
        identity = self.identity(token)
        name = " ".join(name.split())
        if not 1 <= len(name) <= 40 or not name.isprintable() or any(c in name for c in "<>"):
            raise AccountError(422, "Use a display name of 1 to 40 plain-text characters.")
        with self.store.connect() as db:
            db.execute("UPDATE players SET display_name=?,updated_at=? WHERE id=?", (name,int(self.clock()),identity["id"]))
        return self.me(token)

    def sessions(self, token: str) -> list[dict]:
        identity = self.identity(token)
        with self.store.connect() as db:
            rows = db.execute("SELECT id,created_at,expires_at,user_agent FROM player_sessions "
                              "WHERE player_id=? AND revoked_at IS NULL AND expires_at>? ORDER BY created_at DESC,id",
                              (identity["id"],int(self.clock()))).fetchall()
        return [{"id":row[0],"created_at":row[1],"expires_at":row[2],"user_agent":row[3],
                 "current":row[0]==identity["session_id"]} for row in rows]

    def revoke(self, token: str, identifier: str | None = None, all_sessions: bool = False):
        identity = self.identity(token)
        with self.store.connect() as db:
            if all_sessions:
                db.execute("UPDATE player_sessions SET revoked_at=? WHERE player_id=? AND revoked_at IS NULL", (int(self.clock()),identity["id"]))
            else:
                identifier = identifier or identity["session_id"]
                result = db.execute("UPDATE player_sessions SET revoked_at=? WHERE id=? AND player_id=? AND revoked_at IS NULL",
                                    (int(self.clock()),identifier,identity["id"]))
                if result.rowcount != 1:
                    raise AccountError(404, "That player session was not found.")

    def link_demo(self, token: str, demo_token: str) -> dict:
        identity = self.identity(token)
        if not demo_token or not self.store.get(demo_token):
            raise AccountError(409, "Start a demo round in this browser before linking its history.")
        demo_id = self.store.digest(demo_token)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            owner = db.execute("SELECT player_id FROM player_demo_links WHERE demo_id=?", (demo_id,)).fetchone()
            if owner and owner[0] != identity["id"]:
                raise AccountError(409, "This demo history is already linked to another player account.")
            db.execute("INSERT INTO player_demo_links VALUES (?,?,?) ON CONFLICT DO NOTHING", (demo_id,identity["id"],int(self.clock())))
        return self.me(token)

    def save_round(self, demo_token: str, deployment: dict, snapshot: dict):
        if not snapshot["verified"]:
            return
        record = {k:snapshot[k] for k in ("player","round_id","board","finished","verified","won","answer","definition","commitment")}
        with self.store.connect() as db:
            db.execute("INSERT INTO saved_rounds VALUES (?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                       (str(uuid.uuid4()),self.store.digest(demo_token),deployment["address"],int(deployment["chain_id"]),
                        snapshot["round_id"],int(self.clock()),json.dumps(record)))

    def rounds(self, token: str, limit: int, offset: int) -> dict:
        identity = self.identity(token)
        with self.store.connect() as db:
            args = (identity["id"],)
            total = db.execute("SELECT count(*) FROM saved_rounds r JOIN player_demo_links l ON l.demo_id=r.demo_id WHERE l.player_id=?",args).fetchone()[0]
            rows = db.execute("SELECT r.id,r.deployment,r.chain_id,r.completed_at,r.body FROM saved_rounds r "
                              "JOIN player_demo_links l ON l.demo_id=r.demo_id WHERE l.player_id=? "
                              "ORDER BY r.completed_at DESC,r.id LIMIT ? OFFSET ?",(*args,limit,offset)).fetchall()
        return {"total":total,"limit":limit,"offset":offset,"items":[{
            "id":row[0],"deployment":row[1],"chain_id":row[2],"recorded_at":row[3],
            **json.loads(row[4])} for row in rows],"source":"local copies of completed, on-chain-verified demo rounds"}
