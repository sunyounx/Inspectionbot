from __future__ import annotations

import os
import re
from typing import Any

import httpx


def _webhook_url() -> str | None:
    url = (os.getenv("TEAMS_WEBHOOK_URL") or "").strip()
    return url or None


_IMG_HEADER_RE = re.compile(r"^###\s*이미지\s*(\d+)\s*$", re.M)
_SECTION_OK_RE = re.compile(r"^####\s*✅\s*충족\s*항목\s*$", re.M)
_SECTION_WARN_RE = re.compile(r"^####\s*⚠️\s*확인\s*필요\s*항목\s*$", re.M)
_SECTION_BAD_RE = re.compile(r"^####\s*❌\s*명확한\s*이슈\s*$", re.M)
_ITEM_RE = re.compile(r"^\s*-\s*(?:\*\*)?([^:*]+?)(?:\*\*)?\s*:\s*", re.M)


def _extract_items_in_range(text: str, start: int, end: int, limit: int = 4) -> list[str]:
    items: list[str] = []
    for m in _ITEM_RE.finditer(text, start, end):
        name = (m.group(1) or "").strip()
        if not name:
            continue
        if name not in items:
            items.append(name)
        if len(items) >= limit:
            break
    return items


def _first_match_pos(pat: re.Pattern[str], text: str, start: int, end: int) -> int | None:
    m = pat.search(text, start, end)
    return m.start() if m else None


def _per_image_status_lines(feedback: str, max_images: int = 20) -> list[str]:
    """
    feedback 텍스트에서 '### 이미지 N' 섹션을 찾아 이미지별 요약 라인 생성.
    - 가능하면 ✅/⚠️/❌ 섹션의 항목명을 추출해 보여줌
    - 항목명이 없으면 ⚠️/❌ 개수 요약으로 폴백
    """
    text = (feedback or "").strip()
    if not text:
        return []

    matches = list(_IMG_HEADER_RE.finditer(text))
    if not matches:
        # 섹션 헤딩이 없으면 전체만 요약
        warn = text.count("⚠️")
        bad = text.count("❌")
        status = "이슈" if bad else ("확인" if warn else "OK")
        return [f"전체: {status} (⚠️ {warn} · ❌ {bad})"]

    out: list[str] = []
    for idx, m in enumerate(matches[:max_images]):
        n = m.group(1)
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        block = text[start:end]

        # 섹션 위치(없으면 None)
        ok_pos = _first_match_pos(_SECTION_OK_RE, text, start, end)
        warn_pos = _first_match_pos(_SECTION_WARN_RE, text, start, end)
        bad_pos = _first_match_pos(_SECTION_BAD_RE, text, start, end)

        # 섹션 범위 계산(다음 섹션 시작 전까지)
        def section_range(pos: int | None) -> tuple[int, int] | None:
            if pos is None:
                return None
            nexts = [p for p in (ok_pos, warn_pos, bad_pos) if p is not None and p > pos]
            nxt = min(nexts) if nexts else end
            return (pos, nxt)

        ok_items: list[str] = []
        warn_items: list[str] = []
        bad_items: list[str] = []

        r_ok = section_range(ok_pos)
        r_warn = section_range(warn_pos)
        r_bad = section_range(bad_pos)
        if r_ok:
            ok_items = _extract_items_in_range(text, r_ok[0], r_ok[1], limit=3)
        if r_warn:
            warn_items = _extract_items_in_range(text, r_warn[0], r_warn[1], limit=3)
        if r_bad:
            bad_items = _extract_items_in_range(text, r_bad[0], r_bad[1], limit=3)

        if ok_items or warn_items or bad_items:
            segs: list[str] = []
            if ok_items:
                segs.append("✅ " + ", ".join(ok_items))
            if warn_items:
                segs.append("⚠️ " + ", ".join(warn_items))
            if bad_items:
                segs.append("❌ " + ", ".join(bad_items))
            out.append(f"이미지 {n}: " + " | ".join(segs))
        else:
            warn = block.count("⚠️")
            bad = block.count("❌")
            status = "이슈" if bad else ("확인" if warn else "OK")
            out.append(f"이미지 {n}: {status} (⚠️ {warn} · ❌ {bad})")
    return out


async def send_inspection_notification(
    title: str,
    inspection_id: int,
    feedback: str,
    file_count: int,
    issues_count: int,
    drive_url: str | None,
    app_url: str | None,
    image_urls: list[str] | None = None,
    *,
    result_url_query: str | None = None,
) -> dict[str, Any]:
    """
    Teams incoming webhook으로 Adaptive Card 전송.
    TEAMS_WEBHOOK_URL이 없으면 {"skipped": True} 반환.
    """
    webhook = _webhook_url()
    if not webhook:
        return {"skipped": True, "reason": "TEAMS_WEBHOOK_URL not set"}

    summary_line = f"이미지 {int(file_count or 0)}장 검수 완료 · 확인필요 {int(issues_count)}건"
    lines = _per_image_status_lines(feedback)
    lines_text = "\n".join(f"- {x}" for x in lines[:12]) if lines else "- (이미지별 요약을 만들 수 없습니다)"
    web_url = None
    if app_url:
        base = app_url.rstrip("/")
        q = result_url_query or f"gdrive_inspection_id={int(inspection_id)}"
        web_url = f"{base}/static/index.html?{q}"

    card = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.5",
                    "body": [
                        {"type": "TextBlock", "size": "Large", "weight": "Bolder", "text": title},
                        {
                            "type": "FactSet",
                            "facts": [
                                {"title": "Issues", "value": str(int(issues_count))},
                                {"title": "Summary", "value": summary_line},
                            ],
                        },
                        *(
                            [
                                {
                                    "type": "ImageSet",
                                    "images": [
                                        {"type": "Image", "url": u, "size": "medium"}
                                        for u in (image_urls or [])
                                        if (u or "").strip()
                                    ],
                                }
                            ]
                            if (image_urls and any((u or "").strip() for u in image_urls))
                            else []
                        ),
                        {
                            "type": "TextBlock",
                            "text": lines_text,
                            "wrap": True,
                            "spacing": "Medium",
                        },
                    ],
                    "actions": [
                        *(
                            [
                                {
                                    "type": "Action.OpenUrl",
                                    "title": (
                                        "Figma에서 열기"
                                        if "figma.com" in (drive_url or "").lower()
                                        else "Drive 폴더 열기"
                                    ),
                                    "url": drive_url,
                                }
                            ]
                            if drive_url
                            else []
                        ),
                        *(
                            [
                                {
                                    "type": "Action.OpenUrl",
                                    "title": "검수 결과 보기",
                                    "url": web_url,
                                }
                            ]
                            if web_url
                            else []
                        ),
                    ],
                },
            }
        ],
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(webhook, json=card)
        # Teams webhook은 200/202 계열을 반환할 수 있음
        if r.status_code >= 400:
            return {"skipped": False, "ok": False, "status_code": r.status_code, "text": r.text}
        return {"skipped": False, "ok": True, "status_code": r.status_code}


async def send_slack_feedback_notification(
    title: str,
    slack_inspection_id: int,
    original_text: str,
    feedback: str | None,
    file_count: int,
    slack_permalink: str | None,
    app_url: str | None,
    image_urls: list[str] | None = None,
    text_only: bool = False,
) -> dict[str, Any]:
    """
    슬랙 피드백 검수 결과를 Teams로 전송 (Adaptive Card).
    """
    webhook = _webhook_url()
    if not webhook:
        return {"skipped": True, "reason": "TEAMS_WEBHOOK_URL not set"}

    orig = (original_text or "").strip() or "(내용 없음)"
    if len(orig) > 1800:
        orig = orig[:1800] + "…"

    ai_lines: list[str] = []
    fb = (feedback or "").strip()
    if text_only or not fb:
        ai_lines = ["이미지가 첨부되지 않은 피드백입니다. AI 검수를 생략했습니다."]
    else:
        ai_lines = _per_image_status_lines(fb)
        if not ai_lines:
            warn = fb.count("⚠️")
            bad = fb.count("❌")
            ai_lines = [f"요약: ⚠️ {warn} · ❌ {bad} (전체 텍스트는 앱에서 확인)"]

    lines_text = "\n".join(f"- {x}" for x in ai_lines[:16]) if ai_lines else "-"
    detail_url = None
    if app_url:
        base = app_url.rstrip("/")
        detail_url = f"{base}/static/index.html?inspection={int(slack_inspection_id)}"

    body: list[dict[str, Any]] = [
        {"type": "TextBlock", "size": "Large", "weight": "Bolder", "text": title},
        {"type": "TextBlock", "text": "📌 광고주 원문", "weight": "Bolder", "spacing": "Medium"},
        {"type": "TextBlock", "text": orig, "wrap": True},
    ]

    imgs = [u for u in (image_urls or []) if (u or "").strip()]
    if imgs and not text_only:
        body.append(
            {
                "type": "ImageSet",
                "images": [{"type": "Image", "url": u, "size": "medium"} for u in imgs[:10]],
            }
        )

    body.append({"type": "TextBlock", "text": "🤖 AI 검수 결과", "weight": "Bolder", "spacing": "Medium"})
    body.append({"type": "TextBlock", "text": lines_text, "wrap": True})

    actions: list[dict[str, Any]] = []
    if slack_permalink:
        actions.append({"type": "Action.OpenUrl", "title": "슬랙 원문 보기", "url": slack_permalink})
    if detail_url:
        actions.append({"type": "Action.OpenUrl", "title": "검수 상세 보기", "url": detail_url})

    card = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.5",
                    "body": body,
                    "actions": actions,
                },
            }
        ],
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(webhook, json=card)
        if r.status_code >= 400:
            return {"skipped": False, "ok": False, "status_code": r.status_code, "text": r.text}
        return {"skipped": False, "ok": True, "status_code": r.status_code}

