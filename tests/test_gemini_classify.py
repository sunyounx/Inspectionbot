import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.gemini_service import MODEL


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

    system_prompt = """당신은 슬랙 메시지 분류기입니다.
아래 사용자의 슬랙 메시지가 '광고 소재 관련 가이드라인/피드백/방향성'인지 판별하세요.

반드시 JSON으로만 답하세요. 추가 텍스트/마크다운/코드블록 금지.
형식: {"is_feedback": bool, "confidence": 0.0~1.0, "reason": "판별 근거"}
"""

    response_schema = {
        "type": "object",
        "properties": {
            "is_feedback": {"type": "boolean"},
            "confidence": {"type": "number"},
            "reason": {"type": "string"},
        },
        "required": ["is_feedback", "confidence", "reason"],
    }

    samples = [
        "앞으로 배경에 퍼플 톤 비중을 30% 이상으로 올려주세요",
        "다음 미팅 언제예요?",
        "이번 소재 괜찮은 것 같아요",
        "👍",
    ]

    for i, user_message in enumerate(samples, start=1):
        response = client.models.generate_content(
            model=MODEL,
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=response_schema,
            ),
        )

        # google-genai는 보통 response.text에 최종 텍스트가 들어옵니다.
        result = json.loads(response.text)

        print(f"\n=== SAMPLE {i} ===")
        print("INPUT:", user_message)
        print("OUTPUT:", json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
