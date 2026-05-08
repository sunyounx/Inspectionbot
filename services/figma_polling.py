"""Figma 댓글 폴링 — 광고주가 등록 파일에 단 댓글을 pending_approvals에 적재.

원칙:
- Figma에 어떤 메시지도 보내지 않음 (읽기 전용).
- 광고주(handle: FIGMA_ADVERTISER_HANDLES) 댓글이 1개라도 포함된 스레드만 적재.
- 같은 스레드는 1개 pending으로 누적: 새 댓글이 추가되면 기존 pending 흡수 후 신규 적재.
- 댓글이 붙은 노드 PNG를 figma_comment_images에 저장, /api/figma/comment-image/...로 서빙.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

from db.database import (
    absorb_open_pendings_for_thread,
    get_figma_comment_image,
    get_latest_pending_for_source_ts,
    has_open_pending_for_source_ts,
    insert_figma_comment_image,
    insert_message_file,
    insert_pending_approval,
    insert_raw_message,
    pending_source_ts_ever_seen,
    slack_raw_message_ts_exists,
)
from services.figma_service import (
    FigmaRateLimitError,
    build_figma_comment_link,
    download_figma_image,
    export_nodes_as_pngs,
    fetch_file_comments,
    normalize_figma_node_id,
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


def _comment_node_id(c: dict[str, Any]) -> str | None:
    cm = c.get("client_meta") or {}
    if not isinstance(cm, dict):
        return None
    nid = (cm.get("node_id") or "").strip()
    return nid or None


def _save_thread_image(file_key: str, root_id: str, sorted_thread: list[dict[str, Any]]) -> bool:
    """스레드 안에서 가장 먼저 발견되는 node_id로 PNG export 후 저장.
    저장 키는 (file_key, root_id) — serve URL과 일치시킴. 이미 있으면 skip."""
    if get_figma_comment_image(file_key, root_id):
        return True
    node_id: str | None = None
    for c in sorted_thread:
        nid = _comment_node_id(c)
        if nid:
            node_id = nid
            break
    if not node_id:
        return False
    norm = normalize_figma_node_id(node_id)
    try:
        url_map = export_nodes_as_pngs(file_key, [norm], scale=2)
    except FigmaRateLimitError:
        print(f"[figma_poll] rate limit while exporting {file_key}:{node_id}", flush=True)
        return False
    except Exception as e:
        print(f"[figma_poll] export error {file_key}:{node_id}: {e}", flush=True)
        return False
    cdn_url = (url_map or {}).get(norm)
    if not cdn_url:
        return False
    image_bytes = download_figma_image(cdn_url)
    if not image_bytes:
        return False
    try:
        insert_figma_comment_image(
            file_key=file_key,
            comment_id=root_id,
            node_id=norm,
            file_name=f"figma_{file_key}_{root_id}.png",
            mime_type="image/png",
            image_data=image_bytes,
        )
        return True
    except Exception as e:
        print(f"[figma_poll] insert image error {file_key}:{root_id}: {e}", flush=True)
        return False


def _ensure_raw_message_row(file_key: str, root_id: str) -> str:
    """admin UI가 source_ts로 message_files를 조회하므로, 동일 ts의 raw 메시지 row를 1개 만든다."""
    raw_ts = f"figma:{file_key}:{root_id}"
    if slack_raw_message_ts_exists(raw_ts):
        return raw_ts
    try:
        insert_raw_message(
            {
                "ts": raw_ts,
                "channel": f"figma:{file_key}",
                "user_id": None,
                "text": "",
                "is_bot": 0,
                "slack_link": build_figma_comment_link(file_key, root_id),
                "parent_ts": None,
            }
        )
    except Exception as e:
        print(f"[figma_poll] insert_raw_message error {raw_ts}: {e}", flush=True)
    return raw_ts


def _ensure_message_file_row(file_key: str, root_id: str) -> None:
    raw_ts = f"figma:{file_key}:{root_id}"
    try:
        insert_message_file(
            {
                "message_ts": raw_ts,
                "file_id": None,
                "name": f"figma_{file_key}_{root_id}.png",
                "filetype": "png",
                "mimetype": "image/png",
                "url": f"/api/figma/comment-image/{file_key}/{root_id}",
                "is_external": False,
                "external_type": "figma",
                "size": None,
            }
        )
    except Exception as e:
        print(f"[figma_poll] insert_message_file error {raw_ts}: {e}", flush=True)


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

        # 이미지 + raw/message_files row 보장
        image_saved = _save_thread_image(file_key, root_id, sorted_thread)
        _ensure_raw_message_row(file_key, root_id)
        if image_saved:
            _ensure_message_file_row(file_key, root_id)

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
