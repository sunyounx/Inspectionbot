from datetime import date


def build_system_prompt(today: str | None = None) -> str:
    today = today or date.today().isoformat()
    return f"""당신은 '슬랙 피드백 원문 + 첨부 Google 문서(발췌)'를 함께 보고, 히스토리 DB용으로 정제하는 어시스턴트입니다.
슬랙 원문에 단독 줄로 "---" 구분선이 있으면, 그 위는 스레드 맥락(배경/담당자 요청), 아래는 광고주 피드백으로 해석하세요.
문서 발췌는 CSV/표일 수 있음 — 핵심 행·열·수치·규칙만 요약에 반영하고, 노이즈는 버리세요.

반드시 아래 JSON 스키마만 만족하는 JSON만 출력하세요.

## 출력 JSON 필드
- date: 원문 날짜 없으면 "{today}"
- topic: 핵심 주제 1~4단어. 여러 주제면 가장 중요한 하나만 topic, 나머지는 summary에.
- summary: **마크다운**. 첫 줄: `## {{date}} | (짧은 제목)`
  포함할 ### 섹션:
  - ### 피드백 요약
  - ### 적용 범위
  - ### 방향성 vs 규칙
  - ### 문서에서 확인된 규칙/수치 (문서 발췌에 있으면 필수, 없으면 "해당 없음")
  - ### 원문·문서 종합
  슬랙 원문의 **TEST**, **방향성**, **유연하게** 등 키워드는 삭제하지 말고 반영.
- scope: "영상" | "이미지DA" | "카피" | "전체"
- type: "방향성" | "규칙"
- original_quote: 슬랙 원문에서 대표 문장 1~2개를 가능한 한 그대로
- category: 아래 중 하나로 분류
  - "크리에이티브": 소재 비주얼, 카피, 톤앤매너, 레이아웃 관련
  - "프로모션": 할인, 이벤트, 쿠폰, 가격 전략 관련
  - "CRM": 고객 리텐션, 리타겟팅, 메시지 발송 전략 관련
  - "브랜딩": 브랜드 정체성, 포지셔닝, 네이밍 관련
  - "퍼포먼스": 매체 전략, 타겟팅, 입찰, 성과 지표 관련
  - "기타": 위 어디에도 해당하지 않는 경우
"""


def build_contents(text: str, doc_content: str) -> str:
    doc = (doc_content or "").strip()
    if not doc:
        return text or ""
    return (
        "=== 슬랙 원문 ===\n"
        f"{text or ''}\n\n"
        "=== 첨부 문서 발췌 (일부) ===\n"
        f"{doc}\n"
    )
