"""Seed copybank from Google Sheets/Docs exports (one-off).

Env:
  COPYBANK_SOURCES='[{"id":"...","type":"sheets"},{"id":"...","type":"docs"}]'

Usage:
  DATABASE_URL="..." COPYBANK_SOURCES='[...]' python scripts/seed_copybank.py
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio
import json
import os

from dotenv import load_dotenv

from db.database import _connect, init_db, insert_copybank
from services.gdrive_auth import ensure_gdrive_access_token
from services.gdrive_service import read_workspace_document


def _parse_lines(raw: str) -> list[str]:
    out: list[str] = []
    for line in (raw or "").splitlines():
        s = line.strip()
        if not s:
            continue
        # sheets export can be TSV; take first cell as copy candidate
        if "\t" in s:
            s = s.split("\t")[0].strip()
        if len(s) < 2:
            continue
        out.append(s)
    # de-dupe while preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for s in out:
        if s in seen:
            continue
        seen.add(s)
        uniq.append(s)
    return uniq


def main() -> None:
    load_dotenv()
    init_db()

    sources_raw = (os.getenv("COPYBANK_SOURCES") or "").strip()
    if not sources_raw:
        raise RuntimeError("Missing COPYBANK_SOURCES env var")

    # DB에서 OAuth 토큰 가져오기 (refresh_token 포함)
    # - COPYBANK_ACCESS_TOKEN env 없이, DB에 저장된 refresh_token으로 자동 갱신됩니다.
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT session_id FROM gdrive_oauth_tokens ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
    if not row or not row.get("session_id"):
        raise RuntimeError("구글 로그인 세션이 없습니다. 웹에서 먼저 로그인하세요.")
    access_token, _ = asyncio.run(ensure_gdrive_access_token(row["session_id"]))

    sources = json.loads(sources_raw)
    if not isinstance(sources, list):
        raise RuntimeError("COPYBANK_SOURCES must be a JSON array")

    total_inserted = 0
    for src in sources:
        if not isinstance(src, dict):
            continue
        fid = (src.get("id") or "").strip()
        typ = (src.get("type") or "").strip().lower()
        if not fid or typ not in ("sheets", "docs", "slides"):
            continue

        raw = read_workspace_document(fid, typ, access_token) or ""
        lines = _parse_lines(raw)
        inserted = 0
        for s in lines:
            try:
                insert_copybank({"copy_text": s, "source": f"{typ}:{fid}"})
                inserted += 1
            except Exception:
                # allow duplicates/validation errors to be skipped silently
                continue
        total_inserted += inserted
        print(f"[seed_copybank] source={typ}:{fid} inserted={inserted} lines={len(lines)}", flush=True)

    print(f"[seed_copybank] done. total_inserted={total_inserted}", flush=True)


if __name__ == "__main__":
    main()

