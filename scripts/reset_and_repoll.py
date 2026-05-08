"""Reset Slack-derived tables and repoll from a fixed timestamp.

Usage:
  DATABASE_URL="..." SLACK_CHANNEL_ID="..." SLACK_BOT_TOKEN="..." SLACK_ADVERTISER_USER_IDS="U123,..." \
    python scripts/reset_and_repoll.py
"""

from __future__ import annotations

import asyncio
import os

from db.database import _connect, set_poll_state
from services.polling import EARLIEST_TS, poll_and_process_once


def _require_env(name: str) -> None:
    if not (os.getenv(name) or "").strip():
        raise RuntimeError(f"Missing {name} env var")


def reset_tables() -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            # history는 유지
            cur.execute("DELETE FROM slack_inspection_thumbnails")
            cur.execute("DELETE FROM slack_inspections")
            cur.execute("DELETE FROM message_files")
            cur.execute("DELETE FROM pending_approvals")
            cur.execute("DELETE FROM slack_raw_messages")
        conn.commit()


def reset_poll_state() -> None:
    set_poll_state("last_poll_ts", str(EARLIEST_TS))


async def main() -> None:
    _require_env("DATABASE_URL")
    _require_env("SLACK_CHANNEL_ID")
    _require_env("SLACK_BOT_TOKEN")

    print("[reset_and_repoll] clearing tables...", flush=True)
    reset_tables()

    print(f"[reset_and_repoll] reset poll_state last_poll_ts={EARLIEST_TS}", flush=True)
    reset_poll_state()

    print("[reset_and_repoll] polling once...", flush=True)
    n = await poll_and_process_once()
    print(f"[reset_and_repoll] done. processed={n}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

