#!/usr/bin/env python3
"""
Replit/로컬 Shell에서 DB 마이그레이션 실행.

  python scripts/db_migrate.py

DATABASE_URL은 .env 또는 환경 변수에서 읽습니다.
notion_oauth_tokens, approved_history_id 등 init_db() 마이그레이션을 적용합니다.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def main() -> int:
    import os

    if not (os.getenv("DATABASE_URL") or "").strip():
        print("ERROR: DATABASE_URL is not set (.env or Replit Secrets)", file=sys.stderr)
        return 1

    from db.database import init_db

    init_db()
    print("OK: db migrate complete (schema.sql + pending migrations)")
    print("  - notion_oauth_tokens (CREATE IF NOT EXISTS)")
    print("  - pending_approvals.approved_history_id (ADD IF NOT EXISTS)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
