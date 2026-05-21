"""Notion OAuth 세션 (gdrive_session 쿠키와 동일 session_id)."""

from __future__ import annotations

import asyncio
import base64
import os
from typing import Any

import httpx
from fastapi import HTTPException

from db.database import clear_notion_oauth_token, get_notion_oauth_token, upsert_notion_oauth_token


def _oauth_client_id() -> str:
    v = (os.getenv("NOTION_OAUTH_CLIENT_ID") or "").strip()
    if not v:
        raise RuntimeError("Missing NOTION_OAUTH_CLIENT_ID")
    return v


def _oauth_client_secret() -> str:
    v = (os.getenv("NOTION_OAUTH_CLIENT_SECRET") or "").strip()
    if not v:
        raise RuntimeError("Missing NOTION_OAUTH_CLIENT_SECRET")
    return v


def _oauth_redirect_uri() -> str:
    v = (os.getenv("NOTION_OAUTH_REDIRECT_URI") or "").strip()
    if not v:
        raise RuntimeError("Missing NOTION_OAUTH_REDIRECT_URI")
    return v


def _basic_auth_header() -> str:
    raw = f"{_oauth_client_id()}:{_oauth_client_secret()}".encode()
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _owner_email(owner: Any) -> str | None:
    if not isinstance(owner, dict):
        return None
    if (owner.get("type") or "").strip() != "user":
        return None
    user = owner.get("user")
    if not isinstance(user, dict):
        return None
    person = user.get("person")
    if isinstance(person, dict):
        email = (person.get("email") or "").strip()
        if email:
            return email
    return None


def _owner_user_id(owner: Any) -> str | None:
    if not isinstance(owner, dict):
        return None
    if (owner.get("type") or "").strip() != "user":
        return None
    user = owner.get("user")
    if isinstance(user, dict):
        uid = (user.get("id") or "").strip()
        return uid or None
    return None


def exchange_code_for_token(code: str) -> dict[str, Any]:
    code = (code or "").strip()
    if not code:
        raise ValueError("missing code")
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _oauth_redirect_uri(),
    }
    with httpx.Client(timeout=20.0) as client:
        r = client.post(
            "https://api.notion.com/v1/oauth/token",
            headers={
                "Authorization": _basic_auth_header(),
                "Content-Type": "application/json",
            },
            json=payload,
        )
    if r.status_code >= 400:
        raise RuntimeError(f"Notion OAuth token exchange failed: {r.status_code} {r.text[:300]}")
    data = r.json()
    if not isinstance(data, dict):
        raise RuntimeError("Notion OAuth token exchange: invalid response")
    return data


def refresh_notion_token(refresh_token: str) -> dict[str, Any]:
    refresh_token = (refresh_token or "").strip()
    if not refresh_token:
        raise ValueError("missing refresh_token")
    payload = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    with httpx.Client(timeout=20.0) as client:
        r = client.post(
            "https://api.notion.com/v1/oauth/token",
            headers={
                "Authorization": _basic_auth_header(),
                "Content-Type": "application/json",
            },
            json=payload,
        )
    if r.status_code >= 400:
        raise RuntimeError(f"Notion OAuth refresh failed: {r.status_code} {r.text[:300]}")
    data = r.json()
    if not isinstance(data, dict):
        raise RuntimeError("Notion OAuth refresh: invalid response")
    return data


def persist_token_response(session_id: str, data: dict[str, Any]) -> dict[str, Any]:
    access_token = (data.get("access_token") or "").strip()
    if not access_token:
        raise RuntimeError("Notion OAuth: missing access_token")
    refresh_token = (data.get("refresh_token") or "").strip() or None
    workspace_id = (data.get("workspace_id") or "").strip() or None
    workspace_name = (data.get("workspace_name") or "").strip() or None
    bot_id = (data.get("bot_id") or "").strip() or None
    owner = data.get("owner")
    owner_email = _owner_email(owner)
    owner_user_id = _owner_user_id(owner)
    upsert_notion_oauth_token(
        session_id=session_id,
        access_token=access_token,
        refresh_token=refresh_token,
        workspace_id=workspace_id,
        workspace_name=workspace_name,
        bot_id=bot_id,
        owner_user_id=owner_user_id,
        owner_email=owner_email,
    )
    return get_notion_oauth_token(session_id) or {}


async def ensure_notion_access_token(session_id: str) -> tuple[str, dict[str, Any]]:
    """세션 Notion OAuth access_token."""
    tok = get_notion_oauth_token(session_id)
    if not tok:
        raise HTTPException(status_code=401, detail="Notion 연결 필요")

    access_token = (tok.get("access_token") or "").strip()
    if not access_token:
        clear_notion_oauth_token(session_id)
        raise HTTPException(status_code=401, detail="Notion 연결 필요")

    return access_token, tok


async def refresh_notion_access_token(session_id: str) -> tuple[str, dict[str, Any]]:
    tok = get_notion_oauth_token(session_id)
    if not tok:
        raise HTTPException(status_code=401, detail="Notion 연결 필요")
    refresh_token = (tok.get("refresh_token") or "").strip()
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Notion 재연결 필요 (refresh_token 없음)")
    try:
        refreshed = await asyncio.to_thread(refresh_notion_token, refresh_token)
        tok = persist_token_response(session_id, refreshed)
    except Exception as e:
        clear_notion_oauth_token(session_id)
        raise HTTPException(status_code=401, detail=f"Notion 재연결 필요: {e}") from e
    access_token = (tok.get("access_token") or "").strip()
    if not access_token:
        raise HTTPException(status_code=401, detail="Notion 연결 필요")
    return access_token, tok
