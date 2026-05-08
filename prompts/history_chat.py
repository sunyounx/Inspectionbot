from __future__ import annotations

from typing import Any


def build_system_prompt(history: list[dict[str, Any]]) -> str:
    """
    히스토리 조회 모드: DB에 쌓인 히스토리를 근거로 질문에 답변.
    - Slack 전송은 절대 하지 않음(웹앱 답변만)
    """
    lines: list[str] = []
    for idx, item in enumerate(history, start=1):
        date = item.get("date", "")
        topic = item.get("topic", "")
        text = item.get("full_text") or item.get("summary") or ""
        scope = item.get("scope", "")
        typ = item.get("type", "")
        status = item.get("status", "")
        lines.append(f"{idx}. ({date}) [{topic}] (scope: {scope}, type: {typ}, status: {status})\n{text}")

    joined = "\n".join(lines) if lines else "(히스토리 없음)"

    return f"""너는 올더뮤 광고 소재 '히스토리 조회' 어시스턴트야.
사용자의 질문에 대해, 아래 히스토리를 근거로만 요약/인용해서 답해.

규칙:
- 모르는 정보는 추측하지 말고 "히스토리에서 확인되지 않습니다"라고 말해.
- 답변에는 관련 히스토리 항목 번호를 인용해.
- 질문이 모호하면, 먼저 어떤 소재 타입/기간/주제를 찾는지 되물어.

## 히스토리 (최신이 위일 수 있음)
{joined}
"""


def build_contents(message: str):
    return message

