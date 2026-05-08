"""
Google Drive OAuth 세션 쿠키 → access_token 확보(만료 시 refresh).
라우터뿐 아니라 승인 플로우 등 서비스 계층에서 재사용합니다.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Request

from db.database import clear_gdrive_oauth_token, get_gdrive_oauth_token, upsert_gdrive_oauth_token
from services.gdrive_service import refresh_access_token


def get_gdrive_session_id(req: Request) -> str | None:
    sid = (req.cookies.get("gdrive_session") or "").strip()
    return sid or None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_expires_at(v: Any) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        dt = v
    elif isinstance(v, str):
        try:
            dt = datetime.fromisoformat(v)
        except Exception:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def ensure_gdrive_access_token(session_id: str) -> tuple[str, dict[str, Any]]:
    """
    DB에서 토큰을 읽고, 만료면 refresh_token으로 갱신(upsert) 후 access_token 반환.
    실패 시 DB 토큰 행을 정리(clear)하고 401을 raise.
    """
    tok = get_gdrive_oauth_token(session_id)
    if not tok:
        raise HTTPException(status_code=401, detail="Google Drive 로그인 필요")

    access_token = (tok.get("access_token") or "").strip()
    if not access_token:
        clear_gdrive_oauth_token(session_id)
        raise HTTPException(status_code=401, detail="Google Drive 로그인 필요")

    refresh_token = (tok.get("refresh_token") or "").strip() or None
    exp = _parse_expires_at(tok.get("expires_at"))
    need_refresh = bool(exp and exp <= (_utcnow() + timedelta(seconds=60)))

    if need_refresh:
        if not refresh_token:
            clear_gdrive_oauth_token(session_id)
            raise HTTPException(status_code=401, detail="Google Drive 재로그인 필요 (refresh_token 없음)")
        try:
            refreshed = await asyncio.to_thread(refresh_access_token, refresh_token)
        except Exception as e:
            clear_gdrive_oauth_token(session_id)
            raise HTTPException(status_code=401, detail=f"Google Drive 재로그인 필요: {e}") from e
        access_token = refreshed.access_token
        upsert_gdrive_oauth_token(
            session_id=session_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=refreshed.expires_at,
            user_email=(tok.get("user_email") or None),
        )
        tok = get_gdrive_oauth_token(session_id) or tok

    return access_token, tok
