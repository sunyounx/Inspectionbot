from __future__ import annotations

from typing import Any


def build_system_prompt(terms: list[dict[str, Any]]) -> str:
    """
    용어 해석 모드: terms 테이블을 최우선 근거로 용어 설명.
    """
    lines: list[str] = []
    for t in terms:
        term = t.get("term", "")
        definition = t.get("definition", "")
        source = t.get("source") or ""
        suffix = f" (source: {source})" if source else ""
        lines.append(f"- {term}: {definition}{suffix}")

    joined = "\n".join(lines) if lines else "(용어집 없음)"

    return f"""너는 올더뮤 광고 소재 '용어 해석' 어시스턴트야.
아래 용어집(terms)을 최우선 근거로 용어를 설명해.

규칙:
- terms에 정의가 있으면: 그 정의를 기반으로 '짧은 정의 → 실무 예시(1~2개) → 주의점' 순서로 설명해.
- terms에 정의가 없으면: "문서에 명시된 정의는 아니고, 맥락상..."으로 시작해 추론하되 단정하지 말아.
- 질문이 용어가 아니라 검수/히스토리 요청이면, 용어 해석 범위로 돌릴 수 있게 질문을 재정의해.

## 용어집 (terms)
{joined}
"""


def build_contents(message: str):
    return message

