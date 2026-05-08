from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Windows(cp949) 콘솔에서 Slack 텍스트 출력 시 UnicodeEncodeError 방지
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

# python db/test_fetch_files.py 로 실행해도 imports가 동작하도록 프로젝트 루트를 sys.path에 추가
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv()

from db.database import get_files_by_message_ts, get_recent_files, init_db, insert_message_file, insert_raw_message  # noqa: E402
from services.slack_service import build_slack_link, extract_message_files, extract_message_text, fetch_new_messages, is_bot_message  # noqa: E402


def main() -> None:
    channel = os.getenv("SLACK_CHANNEL_ID", "").strip()
    if not channel:
        raise SystemExit("Missing SLACK_CHANNEL_ID in .env")

    since_ts = (sys.argv[1] if len(sys.argv) >= 2 else "").strip()
    if not since_ts:
        raise SystemExit("Usage: python db/test_fetch_files.py <since_ts>")

    init_db()
    messages = fetch_new_messages(channel=channel, since_ts=since_ts)
    print(f"fetched messages: {len(messages)} (since_ts={since_ts})")

    for msg in messages:
        ts = (msg.get("ts") or "").strip()
        if not ts:
            continue

        msg_text = extract_message_text(msg)
        insert_raw_message(
            {
                "ts": ts,
                "channel": channel,
                "user_id": msg.get("user"),
                "text": msg_text,
                "is_bot": is_bot_message(msg),
                "slack_link": build_slack_link(channel=channel, ts=ts),
            }
        )

        files = extract_message_files(msg)
        for f in files:
            f["message_ts"] = ts
            insert_message_file(f)

        if files:
            print(f"- ts={ts} files={len(files)} text={msg_text[:60]!r}")

    print("\nrecent files:")
    for r in get_recent_files(limit=50):
        et = r.get("external_type") or ""
        print(f"- {r.get('message_ts')} {r.get('filetype')}[{et}] {r.get('name')} {r.get('url')}")

    if messages:
        ts0 = (messages[-1].get("ts") or "").strip()
        if ts0:
            print(f"\nfiles for last ts={ts0}:")
            for r in get_files_by_message_ts(ts0):
                print(f"- {r.get('filetype')} {r.get('name')} {r.get('url')}")


if __name__ == "__main__":
    main()

