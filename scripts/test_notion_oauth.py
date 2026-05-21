#!/usr/bin/env python3
"""Notion OAuth 설정·라우트 스모크 테스트. Run: .venv/bin/python scripts/test_notion_oauth.py"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def main() -> int:
    import os
    from urllib.parse import parse_qs, urlparse

    from services.notion_auth import _oauth_client_id, _oauth_redirect_uri

    print("=== 1. env ===")
    for k in ("NOTION_OAUTH_CLIENT_ID", "NOTION_OAUTH_CLIENT_SECRET", "NOTION_OAUTH_REDIRECT_URI"):
        v = (os.getenv(k) or "").strip()
        print(f"  {k}: {'OK' if v else 'MISSING'}")
    cid = _oauth_client_id()
    uri = _oauth_redirect_uri()
    print(f"  redirect_uri: {uri}")
    if not uri.rstrip("/").endswith("/api/notion/oauth/callback"):
        print("  FAIL: redirect_uri must end with /api/notion/oauth/callback")
        return 1

    print("\n=== 2. routes (TestClient, DB lifespan skipped) ===")
    from contextlib import asynccontextmanager

    from fastapi import FastAPI

    from routers import notion_oauth

    @asynccontextmanager
    async def _noop_lifespan(_app: FastAPI):
        yield

    app = FastAPI(lifespan=_noop_lifespan)
    app.include_router(notion_oauth.router)
    from fastapi.testclient import TestClient

    client = TestClient(app)

    r = client.get("/api/notion/oauth/login", follow_redirects=False)
    print(f"  GET /login -> {r.status_code}")
    if r.status_code not in (302, 307):
        print(f"  FAIL body: {r.text[:200]}")
        return 1
    loc = r.headers.get("location") or ""
    print(f"  Location: {loc[:120]}...")
    q = parse_qs(urlparse(loc).query)
    if q.get("client_id", [""])[0] != cid:
        print("  FAIL: client_id mismatch in authorize URL")
        return 1
    if q.get("redirect_uri", [""])[0] != uri:
        print("  FAIL: redirect_uri mismatch in authorize URL")
        return 1
    if "gdrive_session" not in (r.headers.get("set-cookie") or ""):
        print("  WARN: gdrive_session cookie not set")

    r2 = client.get("/api/notion/oauth/status")
    print(f"  GET /status -> {r2.status_code} {r2.json()}")

    print("\n=== 3. token exchange (invalid code — API reachability) ===")
    from services.notion_auth import exchange_code_for_token

    try:
        exchange_code_for_token("invalid-test-code")
        print("  FAIL: expected exchange error")
        return 1
    except Exception as e:
        msg = str(e)
        print(f"  expected error: {msg[:120]}...")
        if "token exchange failed" not in msg.lower() and "invalid" not in msg.lower():
            print("  (Notion API responded — credentials likely valid)")

    print("\n=== 4. optional: session token + page read ===")
    print("  Set TEST_NOTION_ACCESS_TOKEN in .env to run live page read after manual OAuth.")
    test_tok = (os.getenv("TEST_NOTION_ACCESS_TOKEN") or "").strip()
    if test_tok:
        from services.notion_service import read_notion_page

        url = (
            os.getenv("TEST_NOTION_URL")
            or "https://www.notion.so/Brand-OS-v3-0-365b901b86d780409783d813f274f06b"
        )
        text = read_notion_page(url, notion_token=test_tok)
        print(f"  read {url[:60]}... -> {len(text or '')} chars")
        if text:
            print(f"  preview: {text[:200].replace(chr(10), ' ')}...")
    else:
        print("  skip (no TEST_NOTION_ACCESS_TOKEN)")

    print("\nOK — OAuth wiring looks correct. Full flow: deploy Replit + UI 'Notion 연결'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
