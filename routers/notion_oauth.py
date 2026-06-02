from __future__ import annotations

import hashlib
import hmac
import secrets
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from db.database import clear_notion_oauth_token, get_notion_oauth_token
from services.gdrive_auth import get_gdrive_session_id
from services.notion_auth import (
    _oauth_client_id,
    _oauth_client_secret,
    _oauth_redirect_uri,
    exchange_code_for_token,
    persist_token_response,
)
from services.notion_auth import ensure_notion_access_token as _ensure_notion_access_token


router = APIRouter(prefix="/api", tags=["notion"], redirect_slashes=True)


def _ensure_session_cookie(resp: RedirectResponse | JSONResponse, session_id: str) -> None:
    resp.set_cookie(
        key="gdrive_session",
        value=session_id,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
        path="/",
    )


_STATE_COOKIE = "notion_oauth_state"
_STATE_COOKIE_PATH = "/api/notion/oauth"
_STATE_MAX_AGE = 600


def _sign_nonce(nonce: str) -> str:
    key = _oauth_client_secret().encode()
    return hmac.new(key, nonce.encode(), hashlib.sha256).hexdigest()


def _make_state_cookie(nonce: str) -> str:
    return f"{nonce}.{_sign_nonce(nonce)}"


def _verify_state_cookie(cookie_val: str | None, state: str | None) -> bool:
    """콜백 state(쿼리)와 HttpOnly 쿠키(서명된 nonce) 대조 — CSRF 방어."""
    s = (state or "").strip()
    c = (cookie_val or "").strip()
    if not s or "." not in c:
        return False
    nonce, _, sig = c.partition(".")
    if not nonce or not hmac.compare_digest(_sign_nonce(nonce), sig):
        return False
    return hmac.compare_digest(nonce, s)


def _delete_state_cookie(resp: RedirectResponse) -> None:
    resp.delete_cookie(key=_STATE_COOKIE, path=_STATE_COOKIE_PATH)


def _state_redirect(url: str) -> RedirectResponse:
    resp = RedirectResponse(url=url, status_code=302)
    _delete_state_cookie(resp)
    return resp


@router.get("/notion/oauth/login")
def notion_oauth_login(request: Request):
    """Notion OAuth 시작. 랜덤 nonce를 state로 보내고 서명된 HttpOnly 쿠키에 저장(콜백에서 대조)."""
    try:
        client_id = _oauth_client_id()
        redirect_uri = _oauth_redirect_uri()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    sid = get_gdrive_session_id(request) or str(uuid4())
    nonce = secrets.token_urlsafe(24)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "owner": "user",
        "state": nonce,
    }
    url = "https://api.notion.com/v1/oauth/authorize?" + urlencode(params)
    resp = RedirectResponse(url=url, status_code=302)
    _ensure_session_cookie(resp, sid)
    resp.set_cookie(
        key=_STATE_COOKIE,
        value=_make_state_cookie(nonce),
        httponly=True,
        samesite="lax",
        max_age=_STATE_MAX_AGE,
        path=_STATE_COOKIE_PATH,
    )
    return resp


@router.get("/notion/oauth/callback")
async def notion_oauth_callback(
    request: Request,
    code: str | None = None,
    error: str | None = None,
    state: str | None = None,
):
    if (error or "").strip():
        return _state_redirect("/static/index.html?notion_oauth=denied")

    if not _verify_state_cookie(request.cookies.get(_STATE_COOKIE), state):
        return _state_redirect("/static/index.html?notion_oauth=state_error")

    code = (code or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="missing code")

    sid = get_gdrive_session_id(request) or str(uuid4())
    try:
        data = exchange_code_for_token(code)
        persist_token_response(sid, data)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Notion OAuth 실패: {e}") from e

    resp = RedirectResponse(url="/static/index.html?notion_oauth=ok", status_code=302)
    _ensure_session_cookie(resp, sid)
    _delete_state_cookie(resp)
    return resp


@router.get("/notion/oauth/status")
async def notion_oauth_status(request: Request):
    sid = get_gdrive_session_id(request)
    if not sid:
        return {"logged_in": False}
    tok = get_notion_oauth_token(sid)
    if not tok:
        return {"logged_in": False}
    try:
        _, tok2 = await _ensure_notion_access_token(sid)
        return {
            "logged_in": True,
            "owner_email": tok2.get("owner_email"),
            "workspace_name": tok2.get("workspace_name"),
            "has_refresh_token": bool(tok2.get("refresh_token")),
        }
    except HTTPException:
        return {"logged_in": False}


@router.delete("/notion/oauth/logout")
def notion_oauth_logout(request: Request):
    sid = get_gdrive_session_id(request)
    if sid:
        clear_notion_oauth_token(sid)
    return {"ok": True}
