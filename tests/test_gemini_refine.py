import json
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.gemini_service import MODEL


def _as_markdown_card(refined: dict) -> str:
    date_str = str(refined.get("date", "")).strip()
    topic = str(refined.get("topic", "")).strip()
    summary = str(refined.get("summary", "")).strip()
    scope = str(refined.get("scope", "")).strip()
    typ = str(refined.get("type", "")).strip()
    quote = str(refined.get("original_quote", "")).strip()

    title = f"## {date_str} | {topic}"
    body = "\n".join(
        [
            "",
            f"- **피드백 요약**: {summary}",
            f"- **적용 범위**: {scope}",
            f"- **방향성 vs 규칙**: {typ}",
            f'- **원문 발췌**: "{quote}"',
        ]
    )
    return title + body


def main() -> None:
    # Windows 기본 콘솔(cp949)에서 이모지/한글 출력이 깨지거나 예외가 날 수 있어 UTF-8로 강제합니다.
    try:
        import sys

        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY in .env")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    today = date.today().isoformat()

    system_prompt = f"""당신은 '광고 소재 관련 피드백'을 DB에 저장하기 위한 정제기입니다.
입력은 사용자의 원문 피드백 1개입니다.

아래 JSON 스키마를 만족하는 객체를 JSON으로만 출력하세요. (추가 텍스트/마크다운/코드블록 금지)

정제 규칙:
- date: 원문에 날짜가 없으면 "{today}" 사용
- topic: 주제 키워드 1~3단어로 간결하게 (예: "퍼플 비중", "배경 톤")
- summary: 1~2줄 요약 (구체적 행동/규칙이 드러나게)
- scope: "영상" / "이미지DA" / "카피" / "전체" 중 하나로 분류
- type: "방향성" / "규칙" 중 하나로 분류
- original_quote: 원문에서 핵심 문장을 '그대로' 발췌 (원문 훼손 금지)
"""

    response_schema = {
        "type": "object",
        "properties": {
            "date": {"type": "string"},
            "topic": {"type": "string"},
            "summary": {"type": "string"},
            "scope": {"type": "string", "enum": ["영상", "이미지DA", "카피", "전체"]},
            "type": {"type": "string", "enum": ["방향성", "규칙"]},
            "original_quote": {"type": "string"},
        },
        "required": ["date", "topic", "summary", "scope", "type", "original_quote"],
    }

    samples = [
        "앞으로 배경에 퍼플 톤 비중을 30% 이상으로 올려주세요. 그리고 텍스트는 너무 작지 않게 해주세요.",
        "썸네일 카피는 '지금 바로' 같은 직접적인 CTA는 피하고, 톤은 차분하게 가요.",
        "키위포는 메인에는 빼고, 서브 컷에서만 자연스럽게 노출되게 부탁드립니다.",
    ]

    for i, raw_feedback_text in enumerate(samples, start=1):
        response = client.models.generate_content(
            model=MODEL,
            contents=raw_feedback_text,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=response_schema,
            ),
        )

        result = json.loads(response.text)

        print(f"\n=== SAMPLE {i} (MARKDOWN) ===\n")
        print(_as_markdown_card(result))
        print("\n---\n")


if __name__ == "__main__":
    main()
