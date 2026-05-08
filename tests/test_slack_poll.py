import os
import time

from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


def main() -> None:
    # Windows 기본 콘솔(cp949)에서 이모지/한글 출력이 깨지거나 예외가 날 수 있어 UTF-8로 강제합니다.
    try:
        import sys

        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    load_dotenv()

    token = os.getenv("SLACK_USER_TOKEN", "").strip()
    channel = os.getenv("SLACK_CHANNEL_ID", "").strip()
    if not token:
        raise RuntimeError("Missing SLACK_USER_TOKEN in .env")
    if not channel:
        raise RuntimeError("Missing SLACK_CHANNEL_ID in .env")

    client = WebClient(token=token)

    # 최근 10분간 메시지 가져오기
    oldest = str(time.time() - 600)

    try:
        response = client.conversations_history(channel=channel, oldest=oldest, limit=20)
    except SlackApiError as e:
        # e.response["error"] 예: invalid_auth, missing_scope, channel_not_found ...
        raise RuntimeError(f"Slack API error: {e.response.get('error')}") from e

    messages = response.get("messages", [])
    print(f"channel={channel} messages={len(messages)} oldest={oldest}\n")

    # Slack은 최신순으로 반환하는 경우가 많아서 역순으로 출력
    for msg in reversed(messages):
        user = msg.get("user") or msg.get("username") or "unknown"
        text = msg.get("text", "")
        ts = msg.get("ts", "")
        print(f"[{user}] {text}")
        print(f"  ts: {ts}")
        print()


if __name__ == "__main__":
    main()

