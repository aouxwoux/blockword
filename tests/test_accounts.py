import asyncio
from types import SimpleNamespace

import pytest
from aptos_sdk.account import Account
from aptos_sdk.account_address import AccountAddress
from aptos_sdk.async_client import ApiError
from fastapi.testclient import TestClient

import blockword.app as web
from blockword.accounts import Accounts, AccountError, AUTH_COOKIE, CHALLENGE_COOKIE
from blockword.store import Store


class Clock:
    now = 1_800_000_000
    def __call__(self):
        return self.now


class Node:
    def __init__(self):
        self.chain_id, self.keys, self.offline = 249, {}, False

    async def info(self):
        if self.offline:
            raise OSError("offline")
        return {"chain_id":self.chain_id}

    async def account(self, wallet):
        if str(wallet) not in self.keys:
            raise ApiError("not created",404)
        return {"authentication_key":self.keys[str(wallet)]}

    async def close(self):
        pass


@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(web,"DATA",tmp_path)
    with TestClient(web.app) as client:
        service = web.app.state.service
        asyncio.run(service.accounts.close())
        node, clock = Node(), Clock()
        service.accounts = Accounts(service.store,client=node,clock=clock)
        yield client,service,node,clock


def challenge(client,wallet):
    response=client.post("/api/auth/challenge",json={"wallet_address":str(wallet.address())})
    assert response.status_code==200,response.text
    return response.json()


def signed(wallet,request,**replace):
    full=f"APTOS\nnonce: {request['nonce']}\nmessage: {request['message']}"
    result={"challenge_id":request["challenge_id"],"public_key":str(wallet.public_key()),
            "full_message":full,"signature":str(wallet.sign(full.encode()))}
    result.update(replace)
    return result


def login(client,wallet):
    response=client.post("/api/auth/verify",json=signed(wallet,challenge(client,wallet)))
    assert response.status_code==200,response.text
    return response.json(),client.cookies.get(AUTH_COOKIE)


def test_wallet_login_stores_a_profile_and_only_hashed_session_tokens(setup):
    client,service,node,clock=setup
    wallet=Account.generate()
    request=challenge(client,wallet)
    assert "http://testserver" in request["message"]
    assert str(wallet.address()) in request["message"]
    assert request["sign_message"]["address"] is False
    result=client.post("/api/auth/verify",json=signed(wallet,request))
    assert result.status_code==200
    profile=result.json()["player"]
    token=client.cookies.get(AUTH_COOKIE)
    assert profile["wallet_address"]==str(wallet.address())
    assert profile["game_signing"]=="separate server-held demo wallet"
    assert token not in result.text and str(wallet.private_key) not in result.text
    assert "HttpOnly" in result.headers["set-cookie"] and "SameSite=strict" in result.headers["set-cookie"]
    assert client.cookies.get(CHALLENGE_COOKIE) is None
    with service.store.connect() as db:
        stored=db.execute("SELECT token_hash FROM player_sessions").fetchone()[0]
    assert stored==service.store.digest(token) and stored!=token


def test_a_signature_and_nonce_cannot_be_replayed(setup):
    client,service,_,_=setup
    wallet=Account.generate()
    request=challenge(client,wallet)
    binding=client.cookies.get(CHALLENGE_COOKIE)
    payload=signed(wallet,request)
    assert client.post("/api/auth/verify",json=payload).status_code==200
    client.cookies.set(CHALLENGE_COOKIE,binding)
    replay=client.post("/api/auth/verify",json=payload)
    assert replay.status_code==401
    with service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM player_sessions").fetchone()[0]==1


@pytest.mark.parametrize("change",["message","nonce","origin","wallet"])
def test_even_a_valid_signature_over_modified_content_is_rejected(setup,change):
    client,_,_,_=setup
    wallet=Account.generate()
    request=challenge(client,wallet)
    payload=signed(wallet,request)
    replacements={"message":("Blockword sign-in","Some other action"),"nonce":(request["nonce"],"badnonce"),
                  "origin":("http://testserver","https://other.example"),"wallet":(str(wallet.address()),"0x1")}
    before,after=replacements[change]
    payload["full_message"]=payload["full_message"].replace(before,after)
    payload["signature"]=str(wallet.sign(payload["full_message"].encode()))
    assert client.post("/api/auth/verify",json=payload).status_code==401


def test_another_browser_cannot_finish_a_challenge(setup):
    client,_,_,_=setup
    wallet=Account.generate()
    request=challenge(client,wallet)
    client.cookies.clear()
    assert client.post("/api/auth/verify",json=signed(wallet,request)).status_code==401


def test_expired_challenges_and_sessions_are_rejected(setup):
    client,_,_,clock=setup
    wallet=Account.generate()
    request=challenge(client,wallet)
    clock.now+=301
    assert client.post("/api/auth/verify",json=signed(wallet,request)).status_code==401
    login(client,wallet)
    clock.now+=86401
    assert client.get("/api/account/me").status_code==401


def test_current_rotated_key_can_sign_in_and_old_key_cannot(setup):
    client,_,node,_=setup
    original,current=Account.generate(),Account.generate()
    node.keys[str(original.address())]=str(AccountAddress.from_key(current.public_key()))
    request=challenge(client,original)
    assert client.post("/api/auth/verify",json=signed(original,request)).status_code==401
    result=client.post("/api/auth/verify",json=signed(current,request))
    assert result.status_code==200,result.text
    assert result.json()["player"]["wallet_address"]==str(original.address())


def test_an_unrelated_wallet_cannot_claim_a_new_address(setup):
    client,_,_,_=setup
    owner,attacker=Account.generate(),Account.generate()
    request=challenge(client,owner)
    assert client.post("/api/auth/verify",json=signed(attacker,request)).status_code==401


def test_a_new_login_with_a_rotated_key_revokes_older_player_sessions(setup):
    client,service,node,_=setup
    original,current=Account.generate(),Account.generate()
    first,old_token=login(client,original)
    node.keys[str(original.address())]=str(AccountAddress.from_key(current.public_key()))
    client.cookies.clear()
    request=challenge(client,original)
    response=client.post("/api/auth/verify",json=signed(current,request))
    assert response.status_code==200
    assert response.json()["player"]["id"]==first["player"]["id"]
    with pytest.raises(AccountError):
        service.accounts.identity(old_token)


def test_node_failures_do_not_create_sessions(setup):
    client,service,node,_=setup
    wallet=Account.generate()
    request=challenge(client,wallet)
    node.offline=True
    assert client.post("/api/auth/verify",json=signed(wallet,request)).status_code==503
    assert client.get("/api/account/me").status_code==401
    with service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM player_sessions").fetchone()[0]==0


def test_devnet_change_invalidates_the_challenge(setup):
    client,_,node,_=setup
    wallet=Account.generate()
    request=challenge(client,wallet)
    node.chain_id+=1
    assert client.post("/api/auth/verify",json=signed(wallet,request)).status_code==401


def test_profile_persists_across_new_logins_and_session_rotation(setup):
    client,service,_,_=setup
    wallet=Account.generate()
    first,old_token=login(client,wallet)
    result=client.patch("/api/account/me",json={"display_name":"  My Player  "})
    assert result.status_code==200 and result.json()["display_name"]=="My Player"
    again,new_token=login(client,wallet)
    assert again["player"]["id"]==first["player"]["id"]
    assert again["player"]["display_name"]=="My Player" and old_token!=new_token
    with pytest.raises(AccountError):
        service.accounts.identity(old_token)


def test_profile_and_session_access_is_scoped_to_the_signed_in_player(setup):
    client,_,_,_=setup
    first,_=login(client,Account.generate())
    first_session=first["player"]["session_id"]
    client.cookies.clear()
    second,_=login(client,Account.generate())
    assert client.delete(f"/api/account/sessions/{first_session}").status_code==404
    listing=client.get("/api/account/sessions").json()["items"]
    assert len(listing)==1 and listing[0]["id"]==second["player"]["session_id"]


def test_logout_all_revokes_other_browsers_and_current_session(setup):
    client,service,_,_=setup
    wallet=Account.generate()
    _,first=login(client,wallet)
    client.cookies.clear()
    _,second=login(client,wallet)
    assert len(client.get("/api/account/sessions").json()["items"])==2
    assert client.post("/api/auth/logout-all",json={}).status_code==200
    for previous in (first,second):
        with pytest.raises(AccountError):
            service.accounts.identity(previous)
    assert client.cookies.get(AUTH_COOKIE) is None


def test_logout_is_repeatable_and_auth_requires_no_deployer_key(setup):
    client,_,_,_=setup
    assert client.get("/api/config").json()["ready"] is False
    login(client,Account.generate())
    assert client.post("/api/auth/logout",json={}).status_code==200
    assert client.post("/api/auth/logout",json={}).status_code==200
    assert client.get("/api/account/me").status_code==401


def test_cross_site_patch_and_delete_are_blocked(setup):
    client,_,_,_=setup
    profile,_=login(client,Account.generate())
    headers={"Origin":"https://unrelated.example"}
    assert client.patch("/api/account/me",json={"display_name":"No"},headers=headers).status_code==403
    assert client.delete(f"/api/account/sessions/{profile['player']['session_id']}",headers=headers).status_code==403
    assert client.get("/api/account/me").status_code==200
    assert client.patch("/api/account/me",json={"display_name":"No"},
                        headers={"Origin":"https://testserver"}).status_code==403


def test_authentication_rate_limit_is_saved_in_sqlite(setup):
    client,service,_,_=setup
    wallet=Account.generate()
    for _ in range(10):
        assert client.post("/api/auth/challenge",json={"wallet_address":str(wallet.address())}).status_code==200
    assert client.post("/api/auth/challenge",json={"wallet_address":str(wallet.address())}).status_code==429
    with service.store.connect() as db:
        assert db.execute("SELECT max(count) FROM account_rate_limits").fetchone()[0]==11


def test_demo_linking_is_explicit_and_cannot_move_to_another_player(setup):
    client,service,_,_=setup
    demo=Account.generate()
    demo_token="local-demo"
    service.store.put(demo_token,{"key":str(demo.private_key),"secret":None,"receipts":[]})
    client.cookies.set(web.COOKIE,demo_token)
    login(client,Account.generate())
    assert client.get("/api/account/me").json()["linked_demo_accounts"]==0
    assert client.post("/api/account/link-demo",json={}).json()["linked_demo_accounts"]==1
    # an upsert must keep the history links intact.
    service.store.put(demo_token,{"key":str(demo.private_key),"secret":None,"receipts":[],"funded":True})
    assert client.get("/api/account/me").json()["linked_demo_accounts"]==1
    client.cookies.clear()
    client.cookies.set(web.COOKIE,demo_token)
    login(client,Account.generate())
    assert client.post("/api/account/link-demo",json={}).status_code==409


def test_verified_round_history_is_private_persistent_and_paginated(setup):
    client,service,node,clock=setup
    wallet,demo=Account.generate(),Account.generate()
    demo_token="saved-demo"
    service.store.put(demo_token,{"key":str(demo.private_key),"secret":{"answer":"peers"},"receipts":[]})
    client.cookies.set(web.COOKIE,demo_token)
    profile,auth_token=login(client,wallet)
    client.post("/api/account/link-demo",json={})
    snapshot={"player":str(demo.address()),"round_id":1,"board":[{"word":"peers","feedback":[2]*5}],
              "finished":True,"verified":False,"won":True,"answer":"peers","definition":"A peer definition.","commitment":"0xabc"}
    manifest={"address":"0x1","chain_id":249}
    service.accounts.save_round(demo_token,manifest,snapshot)
    assert client.get("/api/account/rounds").json()["total"]==0
    snapshot["verified"]=True
    service.accounts.save_round(demo_token,manifest,snapshot)
    service.accounts.save_round(demo_token,manifest,snapshot)
    result=client.get("/api/account/rounds?limit=1").json()
    assert result["total"]==1 and result["items"][0]["answer"]=="peers"
    assert "secret" not in str(result) and str(demo.private_key) not in str(result)
    assert client.get("/api/account/rounds?limit=0").status_code==422
    # check the profile and history through a fresh connection.
    reopened=Accounts(Store(service.store.path.parent),client=node,clock=clock)
    assert reopened.me(auth_token)["id"]==profile["player"]["id"]
    assert reopened.rounds(auth_token,20,0)["total"]==1
    client.cookies.clear()
    login(client,Account.generate())
    assert client.get("/api/account/rounds").json()["total"]==0


def test_only_one_concurrent_verification_can_consume_a_challenge(tmp_path):
    async def run():
        class BarrierNode(Node):
            def __init__(self):
                super().__init__();self.count=0;self.arrived=asyncio.Event()
            async def account(self,wallet):
                self.count+=1
                if self.count==2:self.arrived.set()
                await self.arrived.wait()
                raise ApiError("new account",404)
        store=Store(tmp_path)
        accounts=Accounts(store,client=BarrierNode(),clock=Clock())
        wallet=Account.generate()
        request,binding=await accounts.challenge(str(wallet.address()),"http://localhost:8000","local")
        payload=signed(wallet,request)
        results=await asyncio.gather(*[accounts.verify(payload,binding,"http://localhost:8000","local","test") for _ in range(2)],return_exceptions=True)
        assert sum(not isinstance(value,Exception) for value in results)==1
        assert sum(isinstance(value,AccountError) for value in results)==1
    asyncio.run(run())


def test_account_tables_can_be_added_without_replacing_an_existing_demo_session(tmp_path):
    import sqlite3,json
    with sqlite3.connect(tmp_path/"sessions.sqlite3") as db:
        db.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY,body TEXT NOT NULL)")
        db.execute("INSERT INTO sessions VALUES (?,?)",(Store.digest("old-demo"),json.dumps({"secret":"kept","receipts":[]})))
    store=Store(tmp_path)
    Accounts(store,client=Node(),clock=Clock())
    assert store.get("old-demo")=={"secret":"kept","receipts":[]}
    assert store.count()==1


def test_failed_database_operation_rolls_back_and_closes_connection(tmp_path):
    import sqlite3
    store=Store(tmp_path)
    with pytest.raises(RuntimeError):
        with store.connect() as db:
            db.execute("INSERT INTO sessions VALUES ('unfinished','{}')")
            raise RuntimeError("interrupted")
    assert store.count()==0
    with pytest.raises(sqlite3.ProgrammingError,match="closed"):
        db.execute("SELECT 1")
