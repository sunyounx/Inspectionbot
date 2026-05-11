"""Figma 댓글 폴링 — 광고주가 등록 파일에 단 댓글을 pending_approvals에 적재.

원칙:
- Figma에 어떤 메시지도 보내지 않음 (읽기 전용).
- 광고주(handle: FIGMA_ADVERTISER_HANDLES) 댓글이 1개라도 포함된 스레드만 적재.
- 같은 스레드는 1개 pending으로 누적: 새 댓글이 추가되면 기존 pending 흡수 후 신규 적재.
- 이미지 export는 하지 않음. 어드민 카드는 댓글 텍스트 + Figma 링크(slack_link)만 표시.
  (Figma 플랜에 따라 image export가 막혀서 'File not exportable' 403이 발생하기 때문.)
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

from db.database import (
    absorb_open_pendings_for_thread,
    get_latest_pending_for_source_ts,
    has_open_pending_for_source_ts,
    insert_pending_approval,
    pending_source_ts_ever_seen,
)
from services.figma_service import (
    FigmaRateLimitError,
    build_figma_comment_link,
    fetch_file_comments,
)

KST = timezone(timedelta(hours=9))


def _watched_file_keys() -> list[str]:
    raw = os.getenv("FIGMA_WATCHED_FILE_KEYS", "") or ""
    return [k.strip() for k in raw.split(",") if k.strip()]


def _advertiser_handles() -> set[str]:
    raw = os.getenv("FIGMA_ADVERTISER_HANDLES", "") or ""
    return {h.strip() for h in raw.split(",") if h.strip()}


def _comment_thread_root(c: dict[str, Any]) -> str:
    """parent_id가 있으면 그것이 root, 없으면 자기 자신이 root."""
    pid = (c.get("parent_id") or "").strip()
    return pid or (c.get("id") or "").strip()


def _parse_figma_iso(s: str) -> float:
    """Figma created_at(ISO 8601 UTC) → epoch seconds. 실패 시 0."""
    if not s:
        return 0.0
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _author_label(c: dict[str, Any]) -> str:
    u = c.get("user") or {}
    if isinstance(u, dict):
        return (u.get("handle") or "").strip() or (u.get("id") or "").strip() or "(unknown)"
    return "(unknown)"


def _format_thread_full_text(sorted_thread: list[dict[str, Any]]) -> str:
    """parent + 답글 시간순 누적. 각 줄에 [작성자] prefix."""
    blocks: list[str] = []
    for c in sorted_thread:
        msg = (c.get("message") or "").strip()
        if not msg:
            continue
        blocks.append(f"[{_author_label(c)}] {msg}")
    return "\n---\n".join(blocks)


async def _process_file(file_key: str, advertiser_handles: set[str]) -> int:
    try:
        comments = await asyncio.to_thread(fetch_file_comments, file_key)
    except FigmaRateLimitError:
        print(f"[figma_poll] rate limit on comments fetch {file_key}", flush=True)
        return 0
    except Exception as e:
        print(f"[figma_poll] fetch comments error {file_key}: {e}", flush=True)
        return 0

    if not comments:
        return 0

    threads: dict[str, list[dict[str, Any]]] = {}
    for c in comments:
        root = _comment_thread_root(c)
        if not root:
            continue
        threads.setdefault(root, []).append(c)

    processed = 0
    for root_id, thread in threads.items():
        if advertiser_handles and not any(_author_label(c) in advertiser_handles for c in thread):
            continue

        source_ts = f"figma:{file_key}:{root_id}"

        # 승인/폐기로 닫힌 스레드는 다시 적재하지 않음.
        if pending_source_ts_ever_seen(source_ts) and not has_open_pending_for_source_ts(source_ts):
            continue

        sorted_thread = sorted(thread, key=lambda c: _parse_figma_iso(c.get("created_at") or ""))

        full_text = _format_thread_full_text(sorted_thread)
        if not full_text:
            continue

        # 변경 없으면 skip — 기존 pending(있으면)의 full_text와 동일하면 폴링 cycle마다 재insert 방지
        existing = get_latest_pending_for_source_ts(source_ts)
        if existing and (existing.get("full_text") or "") == full_text:
            continue

        # 기존 대기 pending이 있으면 흡수 후 누적 신규 적재 (Slack 패턴 동일)
        if has_open_pending_for_source_ts(source_ts):
            absorb_open_pendings_for_thread(source_ts)

        latest = sorted_thread[-1]
        latest_ts = _parse_figma_iso(latest.get("created_at") or "")
        message_time = (
            datetime.fromtimestamp(latest_ts, tz=KST).strftime("%Y-%m-%d %H:%M:%S")
            if latest_ts > 0
            else None
        )

        adv_authors = [c for c in sorted_thread if _author_label(c) in advertiser_handles]
        author_src = adv_authors[-1] if adv_authors else latest
        author_user = author_src.get("user") if isinstance(author_src.get("user"), dict) else {}
        author_user = author_user or {}

        try:
            insert_pending_approval(
                {
                    "date": date.today().isoformat(),
                    "topic": "",
                    "summary": "",
                    "scope": "전체",
                    "type": "방향성",
                    "category": "미분류",
                    "full_text": full_text,
                    "original_quote": "",
                    "slack_link": build_figma_comment_link(file_key, root_id),
                    "source_ts": source_ts,
                    "parent_ts": None,
                    "author_user_id": (author_user.get("id") or "").strip() or None,
                    "author_name": _author_label(author_src),
                    "message_time": message_time,
                    "has_conflict": 0,
                    "status": "대기중",
                }
            )
            processed += 1
        except Exception as e:
            print(f"[figma_poll] insert_pending error {source_ts}: {e}", flush=True)

    return processed


async def figma_poll_once() -> int:
    file_keys = _watched_file_keys()
    if not file_keys:
        return 0
    advertiser_handles = _advertiser_handles()
    total = 0
    for fk in file_keys:
        try:
            total += await _process_file(fk, advertiser_handles)
        except Exception as e:
            print(f"[figma_poll] file error {fk}: {e}", flush=True)
    return total


async def figma_poll_loop() -> None:
    interval_min = int(os.getenv("POLL_INTERVAL_MINUTES", "3"))
    interval_sec = max(10, interval_min * 60)
    while True:
        try:
            await figma_poll_once()
        except Exception as e:
            print(f"[figma_poll_loop] error: {e}", flush=True)
        await asyncio.sleep(interval_sec)
