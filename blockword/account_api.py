from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, Field

from .accounts import AUTH_COOKIE, CHALLENGE_COOKIE, CHALLENGE_TTL, SESSION_TTL
from .hosting import request_origin, secure_cookie

router = APIRouter()


def accounts(request):
    return request.app.state.service.accounts


def token(request):
    return request.cookies.get(AUTH_COOKIE, "")


def origin(request):
    return request_origin(request)


def actor(request):
    # use the direct peer address; visitors behind a proxy may share this limit.
    return request.client.host if request.client else "local"


class ChallengeInput(BaseModel):
    wallet_address: str = Field(min_length=1, max_length=66)


class VerifyInput(BaseModel):
    challenge_id: str = Field(min_length=36, max_length=36)
    public_key: str = Field(pattern="^0x[0-9a-fA-F]{64}$")
    signature: str = Field(pattern="^0x[0-9a-fA-F]{128}$")
    full_message: str = Field(min_length=1, max_length=4096)


class ProfileInput(BaseModel):
    display_name: str = Field(min_length=1, max_length=40)


@router.get("/api/auth/config")
async def auth_config():
    return {"network":"devnet","signing_scheme":"ed25519","challenge_ttl":CHALLENGE_TTL,
            "session_ttl":SESSION_TTL,"transaction_permission":False}


@router.post("/api/auth/challenge")
async def challenge(payload: ChallengeInput, request: Request, response: Response):
    body, binding = await accounts(request).challenge(payload.wallet_address,origin(request),actor(request))
    response.set_cookie(CHALLENGE_COOKIE,binding,httponly=True,samesite="strict",
                        secure=secure_cookie(request),max_age=CHALLENGE_TTL)
    return body


@router.post("/api/auth/verify")
async def verify(payload: VerifyInput, request: Request, response: Response):
    profile, session_token, expires_at = await accounts(request).verify(
        payload.model_dump(),request.cookies.get(CHALLENGE_COOKIE,""),origin(request),actor(request),
        request.headers.get("user-agent",""),token(request))
    response.set_cookie(AUTH_COOKIE,session_token,httponly=True,samesite="strict",
                        secure=secure_cookie(request),max_age=SESSION_TTL)
    response.delete_cookie(CHALLENGE_COOKIE,samesite="strict",secure=secure_cookie(request))
    return {"player":profile,"expires_at":expires_at}


@router.get("/api/account/me")
async def me(request: Request):
    return accounts(request).me(token(request))


@router.patch("/api/account/me")
async def rename(payload: ProfileInput, request: Request):
    accounts(request).throttle("profile",actor(request),30)
    return accounts(request).rename(token(request),payload.display_name)


@router.get("/api/account/sessions")
async def sessions(request: Request):
    return {"items":accounts(request).sessions(token(request))}


@router.delete("/api/account/sessions/{identifier}")
async def revoke(identifier: str, request: Request, response: Response):
    account = accounts(request)
    current = account.identity(token(request))["session_id"]
    account.revoke(token(request),identifier=identifier)
    if identifier == current:
        response.delete_cookie(AUTH_COOKIE,samesite="strict",secure=secure_cookie(request))
    return {"revoked":True,"current":identifier == current}


@router.post("/api/auth/logout")
async def logout(request: Request, response: Response):
    from .accounts import AccountError
    try:
        accounts(request).revoke(token(request))
    except AccountError as exc:
        if exc.status != 401:
            raise
    response.delete_cookie(AUTH_COOKIE,samesite="strict",secure=secure_cookie(request))
    return {"signed_out":True}


@router.post("/api/auth/logout-all")
async def logout_all(request: Request, response: Response):
    accounts(request).revoke(token(request),all_sessions=True)
    response.delete_cookie(AUTH_COOKIE,samesite="strict",secure=secure_cookie(request))
    return {"signed_out":True}


@router.post("/api/account/link-demo")
async def link_demo(request: Request):
    return accounts(request).link_demo(token(request),request.cookies.get("blockword_session",""))


@router.get("/api/account/rounds")
async def rounds(request: Request, limit: int = Query(default=20,ge=1,le=50), offset: int = Query(default=0,ge=0)):
    return accounts(request).rounds(token(request),limit,offset)
