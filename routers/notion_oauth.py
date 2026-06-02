from __future__ import annotations

import secrets
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

from db.database import clear_notion_oauth_token, get_notion_oauth_token
from services.gdrive_auth import get_gdrive_session_id
from services.notion_auth import (
    _oauth_client_id,
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


def _build_oauth_state(pending_id: int | None, action: str | None) -> str:
    if pending_id is not None:
        act = (action or "approve").strip() or "approve"
        return f"pending:{int(pending_id)}:{act}"
    return secrets.token_urlsafe(16)


def _parse_oauth_state(state: str | None) -> tuple[int | None, str | None]:
    s = (state or "").strip()
    if not s.startswith("pending:"):
        return None, None
    parts = s.split(":", 2)
    if len(parts) < 2:
        return None, None
    try:
        pid = int(parts[1])
    except ValueError:
        return None, None
    act = parts[2].strip() if len(parts) > 2 else "approve"
    return pid, act or "approve"


@router.get("/notion/oauth/login")
def notion_oauth_login(
    request: Request,
    pending_id: int | None = Query(None, ge=1),
    action: str = Query("approve"),
):
    """승인 시 Notion 필요할 때만 호출. pending_id 있으면 콜백 후 해당 승인 자동 재시도."""
    try:
        client_id = _oauth_client_id()
        redirect_uri = _oauth_redirect_uri()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    sid = get_gdrive_session_id(request) or str(uuid4())
    state = _build_oauth_state(pending_id, action)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "owner": "user",
        "state": state,
    }
    url = "https://api.notion.com/v1/oauth/authorize?" + urlencode(params)
    resp = RedirectResponse(url=url, status_code=302)
    _ensure_session_cookie(resp, sid)
    return resp


@router.get("/notion/oauth/callback")
async def notion_oauth_callback(
    request: Request,
    code: str | None = None,
    error: str | None = None,
    state: str | None = None,
):
    if (error or "").strip():
        return RedirectResponse(url="/static/index.html?notion_oauth=denied", status_code=302)
    code = (code or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="missing code")

    sid = get_gdrive_session_id(request) or str(uuid4())
    try:
        data = exchange_code_for_token(code)
        persist_token_response(sid, data)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Notion OAuth 실패: {e}") from e

    pid, act = _parse_oauth_state(state)
    if pid is not None:
        dest = (
            f"/static/index.html?notion_oauth=ok"
            f"&resume_pending={pid}&resume_action={act or 'approve'}"
        )
    else:
        dest = "/static/index.html?notion_oauth=ok"
    resp = RedirectResponse(url=dest, status_code=302)
    _ensure_session_cookie(resp, sid)
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
