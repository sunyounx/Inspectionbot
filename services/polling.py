from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

from db.database import (
    absorb_parent_pending_if_any,
    get_raw_message_by_ts,
    get_top_level_raw_since,
    has_open_pending_for_source_ts,
    insert_message_file,
    insert_pending_approval,
    insert_raw_message,
    slack_raw_message_ts_exists,
    update_raw_message_feedback,
)
from services.poll_state import load_last_poll_ts, save_last_poll_ts
from services.slack_service import (
    build_slack_link,
    clean_slack_markup,
    extract_message_files,
    extract_message_text,
    fetch_new_messages,
    fetch_thread_replies,
    get_user_name,
    is_bot_message,
    resolve_mentions,
)

KST = timezone(timedelta(hours=9))

EARLIEST_TS = "1774828800"  # 2026-04-01 00:00:00 UTC

ADVERTISER_IDS = {
    uid.strip()
    for uid in (os.getenv("SLACK_ADVERTISER_USER_IDS", "") or "").split(",")
    if uid.strip()
}


def _slack_plain_text(msg: dict[str, Any]) -> str:
    t = extract_message_text(msg)
    t = resolve_mentions(t)
    return clean_slack_markup(t)


def _persist_message_and_files(channel: str, msg: dict[str, Any], *, parent_ts: str | None) -> None:
    ts = (msg.get("ts") or "").strip()
    if not ts:
        return
    text = _slack_plain_text(msg)
    insert_raw_message(
        {
            "ts": ts,
            "channel": channel,
            "user_id": msg.get("user"),
            "text": text,
            "is_bot": is_bot_message(msg),
            "slack_link": build_slack_link(channel=channel, ts=ts),
            "parent_ts": parent_ts,
        }
    )
    try:
        files = extract_message_files(msg)
        for f in files:
            f["message_ts"] = ts
            insert_message_file(f)
    except Exception as e:
        print(f"[poll] extract/insert files error ts={ts}: {e}")


async def _process_potential_feedback(
    *,
    channel: str,
    text: str,
    message_ts: str,
    user_id: str | None,
    parent_ts: str | None = None,
) -> None:
    """광고주 원문 메시지를 pending_approvals에 그대로 적재 (Gemini 호출 0회)."""
    # 광고주 메시지만 처리(환경변수 SLACK_ADVERTISER_USER_IDS가 비어 있으면 기존 동작 유지)
    is_advertiser = bool(ADVERTISER_IDS) and (user_id or "") in ADVERTISER_IDS
    if ADVERTISER_IDS and not is_advertiser:
        return
    if not (text or "").strip():
        return
    if has_open_pending_for_source_ts(message_ts):
        return
    # 광고주 메시지는 무조건 피드백으로 마킹하고 pending에 적재
    update_raw_message_feedback(message_ts, 1)

    slack_link = build_slack_link(channel=channel, ts=message_ts)

    try:
        ts_f = float(message_ts) if message_ts else 0.0
    except (TypeError, ValueError):
        ts_f = 0.0
    if ts_f > 0:
        message_time = datetime.fromtimestamp(ts_f, tz=KST).strftime("%Y-%m-%d %H:%M:%S")
    else:
        message_time = None

    author_uid = (user_id or "").strip()
    author_name = get_user_name(author_uid) if author_uid else None

    pt = (parent_ts or "").strip() or None

    if pt:
        parent = get_raw_message_by_ts(pt)
        parent_text = (parent or {}).get("text") or ""
        if parent_text.strip():
            full_text_for_pending = f"{parent_text}\n---\n{text}"
        else:
            full_text_for_pending = text
    else:
        full_text_for_pending = text

    if pt:
        absorb_parent_pending_if_any(pt)

    insert_pending_approval(
        {
            "date": date.today().isoformat(),
            "topic": "",
            "summary": "",
            "scope": "전체",
            "type": "방향성",
            "category": "미분류",
            "full_text": full_text_for_pending,
            "original_quote": "",
            "slack_link": slack_link,
            "source_ts": message_ts,
            "parent_ts": pt,
            "author_user_id": author_uid or None,
            "author_name": author_name,
            "message_time": message_time,
            "has_conflict": 0,
            "status": "대기중",
        }
    )


async def _rescan_recent_threads(channel: str, days: int = 3) -> None:
    ts_floor = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
    top = get_top_level_raw_since(ts_floor)
    for row in top:
        root_ts = (row.get("ts") or "").strip()
        if not root_ts:
            continue
        try:
            thread_msgs = fetch_thread_replies(channel, root_ts)
        except Exception as e:
            print(f"[poll] rescan fetch_thread_replies error ts={root_ts}: {e}")
            continue
        for reply in thread_msgs:
            rts = (reply.get("ts") or "").strip()
            if not rts:
                continue
            if slack_raw_message_ts_exists(rts):
                continue
            _persist_message_and_files(channel, reply, parent_ts=root_ts)
            reply_text = _slack_plain_text(reply)
            if is_bot_message(reply) or not reply_text.strip():
                continue
            await _process_potential_feedback(
                channel=channel,
                text=reply_text,
                message_ts=rts,
                user_id=reply.get("user"),
                parent_ts=root_ts,
            )


async def poll_and_process_once() -> int:
    """
    Slack에서 새 메시지를 읽고(전송 금지), 원문 아카이브 + pending_approvals에 저장.
    반환값: 처리된 메시지 수(저장 여부와 무관)
    """
    channel = os.getenv("SLACK_CHANNEL_ID", "").strip()
    if not channel:
        raise RuntimeError("Missing SLACK_CHANNEL_ID in .env")

    since_ts = load_last_poll_ts()
    if float(since_ts) < float(EARLIEST_TS):
        since_ts = EARLIEST_TS
    messages = fetch_new_messages(channel=channel, since_ts=since_ts)

    processed = 0
    newest_ts = float(since_ts or "0")

    for msg in messages:
        processed += 1
        ts = msg.get("ts") or ""
        try:
            newest_ts = max(newest_ts, float(ts))
        except Exception:
            pass

        msg_text = _slack_plain_text(msg)
        th = msg.get("thread_ts")
        is_reply_in_history = bool(th) and th != ts
        effective_parent = th if is_reply_in_history else None

        _persist_message_and_files(channel, msg, parent_ts=effective_parent)

        try:
            reply_n = int(float(msg.get("reply_count") or 0))
        except (TypeError, ValueError):
            reply_n = 0

        if not is_reply_in_history:
            # 최상위: 부모 pending을 먼저 넣어야 댓글에서 absorb_parent_pending_if_any가 동작함
            if not is_bot_message(msg) and msg_text.strip():
                await _process_potential_feedback(
                    channel=channel,
                    text=msg_text,
                    message_ts=ts,
                    user_id=msg.get("user"),
                    parent_ts=None,
                )
            if reply_n > 0 and ts:
                try:
                    thread_msgs = fetch_thread_replies(channel, ts)
                except Exception as e:
                    print(f"[poll] fetch_thread_replies error ts={ts}: {e}")
                    thread_msgs = []
                for reply in thread_msgs:
                    rts = reply.get("ts") or ""
                    if not rts:
                        continue
                    reply_text = _slack_plain_text(reply)
                    _persist_message_and_files(channel, reply, parent_ts=ts)
                    if is_bot_message(reply):
                        continue
                    if not reply_text.strip():
                        continue
                    await _process_potential_feedback(
                        channel=channel,
                        text=reply_text,
                        message_ts=rts,
                        user_id=reply.get("user"),
                        parent_ts=ts,
                    )
        else:
            # thread_broadcast 등 채널에 노출된 답글: 스레드 드릴 없음
            if not is_bot_message(msg) and msg_text.strip():
                await _process_potential_feedback(
                    channel=channel,
                    text=msg_text,
                    message_ts=ts,
                    user_id=msg.get("user"),
                    parent_ts=effective_parent,
                )

    await _rescan_recent_threads(channel)

    if newest_ts > 0:
        save_last_poll_ts(str(newest_ts + 0.001))

    return processed


async def poll_slack_loop() -> None:
    """
    무한 폴링 루프. Slack에는 절대 전송하지 않음.
    """
    interval_min = int(os.getenv("POLL_INTERVAL_MINUTES", "3"))
    interval_sec = max(10, interval_min * 60)

    while True:
        try:
            await poll_and_process_once()
        except Exception as e:
            print(f"[poll_slack_loop] error: {e}")
        await asyncio.sleep(interval_sec)
