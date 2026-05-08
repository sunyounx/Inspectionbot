from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

KST = timezone(timedelta(hours=9))


def _fmt_time_from_ts(ts_str: str) -> str:
    try:
        return datetime.fromtimestamp(float(ts_str), tz=KST).strftime("%H:%M")
    except Exception:
        return "—"


def _one_block(idx_label: str, m: dict[str, Any], *, indent: str = "") -> str:
    text = (m.get("text") or "").strip() or "(내용 없음)"
    uid = m.get("user_id") or "—"
    ca = m.get("created_at") or "—"
    ts = m.get("ts") or ""
    is_bot = int(m.get("is_bot") or 0) == 1
    role = "봇" if is_bot else "사용자"
    fb = m.get("is_feedback")
    if fb == 1:
        fl = "피드백(분류됨)"
    elif fb == 0:
        fl = "비피드백(분류됨)"
    else:
        fl = "미분류"
    link = m.get("slack_link") or ""
    link_note = f" link:{link}" if link else ""
    return f"{indent}{idx_label}. [{ca}] ts:{ts} user:{uid} ({role}, {fl}){link_note}\n{text}"


def build_system_prompt(
    raw_messages: list[dict[str, Any]],
    thread_replies: dict[str, list[dict[str, Any]]],
) -> str:
    """
    슬랙 원본 메시지 아카이브 기반 검색 모드.
    상위 메시지마다 스레드 댓글을 들여쓰기로 포함.
    """
    lines: list[str] = []
    n_rules = 0
    for i, m in enumerate(raw_messages, start=1):
        lines.append(_one_block(str(i), m))
        n_rules += 1
        pts = (m.get("ts") or "").strip()
        children = thread_replies.get(pts, []) if pts else []
        for j, child in enumerate(children, start=1):
            ch_time = _fmt_time_from_ts((child.get("ts") or ""))
            ctext = (child.get("text") or "").strip() or "(내용 없음)"
            uid = child.get("user_id") or "—"
            is_bot = int(child.get("is_bot") or 0) == 1
            role = "봇" if is_bot else "사용자"
            lines.append(
                f'   └ {i}-{j}. [{ch_time}] user:{uid} ({role}) "{ctext}"'
            )
            n_rules += 1

    joined = "\n".join(lines) if lines else "(원문 없음)"

    return f"""너는 올더뮤 광고 소재 검수팀을 위한 '슬랙 원본 메시지 검색' 어시스턴트야.
아래는 DB에 아카이브된 **슬랙 채널 원문** 일부다(필터·정렬이 적용된 목록, 상위 메시지별로 스레드 댓글이 들여쓰기로 붙어 있음).
사용자 질문에 대해 **이 목록에 근거해** 요약·인용·찾기 결과를 한국어로 답해.

규칙:
- 목록에 없는 내용은 추측하지 말고 "제공된 원문 범위에서는 확인되지 않습니다"라고 말해.
- 답변에 관련 항목 번호(1., 2., … 또는 1-1., 1-2. 등)를 인용해.
- '지난주' 등 기간 질문은, 목록에 해당 시점 메시지가 없으면 범위 한계를 설명해.
- Slack으로 메시지를 보내거나 어떤 행동도 하지 마. 텍스트 답변만.

## 원본 메시지 (총 {n_rules}개 항목: 상위 + 스레드 댓글)
{joined}
"""
