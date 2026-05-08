from __future__ import annotations

import os
import ipaddress
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse, StreamingResponse
from starlette.background import BackgroundTask


router = APIRouter(prefix="/api", tags=["files"], redirect_slashes=True)


def _is_blocked_host(host: str) -> bool:
    h = (host or "").strip().lower()
    if not h:
        return True
    if h in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
        return True
    # IP literal 차단 (private/loopback/link-local 등)
    try:
        ip = ipaddress.ip_address(h)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return True
    except ValueError:
        pass
    return False


def _is_slack_files_url(url: str) -> bool:
    try:
        u = urlparse(url)
    except Exception:
        return False
    if (u.scheme or "").lower() not in ("https", "http"):
        return False
    host = (u.netloc or "").lower()
    return host == "files.slack.com"


@router.get("/files/download")
async def download(url: str = Query(..., description="원본 파일 URL (url_private 등)")):
    url = (url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")

    ul = url.lower()
    if "localhost" in ul or "127.0.0.1" in ul or "[::1]" in ul:
        raise HTTPException(status_code=400, detail="blocked host")

    try:
        u = urlparse(url)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid url")

    if _is_blocked_host(u.hostname or ""):
        raise HTTPException(status_code=400, detail="blocked host")

    # SSRF 방지: Slack 업로드만 프록시. 나머지는 브라우저 리다이렉트.
    if not _is_slack_files_url(url):
        return RedirectResponse(url=url, status_code=307)

    token = (os.getenv("SLACK_USER_TOKEN") or "").strip()
    if not token:
        raise HTTPException(status_code=500, detail="Missing SLACK_USER_TOKEN")

    headers = {"Authorization": f"Bearer {token}", "Cookie": f"d={token}"}

    client = httpx.AsyncClient(follow_redirects=True, timeout=60.0)
    resp: httpx.Response | None = None
    try:
        resp = await client.send(client.build_request("GET", url, headers=headers), stream=True)
        if resp.status_code >= 400:
            await resp.aclose()
            await client.aclose()
            if resp.status_code == 401:
                raise HTTPException(status_code=401, detail="Slack 인증 오류 (token invalid/expired)")
            raise HTTPException(status_code=502, detail=f"Slack fetch failed: HTTP {resp.status_code}")

        ct = resp.headers.get("content-type") or "application/octet-stream"
        cd = resp.headers.get("content-disposition")

        headers_out = {}
        if cd:
            headers_out["Content-Disposition"] = cd

        async def cleanup() -> None:
            await resp.aclose()
            await client.aclose()

        return StreamingResponse(
            resp.aiter_bytes(),
            media_type=ct,
            headers=headers_out,
            background=BackgroundTask(cleanup),
        )
    except HTTPException:
        raise
    except Exception as e:
        if resp is not None:
            await resp.aclose()
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"Slack fetch failed: {e}") from e

