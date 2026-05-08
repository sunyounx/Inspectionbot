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

    load_dotenv()

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY in .env")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    system_prompt = """당신은 광고 소재 가이드라인 히스토리 '충돌 감지기'입니다.
입력으로 기존 히스토리 1건과 신규 피드백 1건이 주어집니다.

다음 기준으로 충돌 여부를 판정하세요:
- 충돌(conflicts=true): 두 문장이 같은 주제에 대해 '서로 반대되는 지시/금지/허용'을 말함 (예: "제외" vs "노출")
- 비충돌(conflicts=false): 서로 다른 요소를 다루거나, 동시에 성립 가능함

반드시 JSON으로만 출력하세요. 추가 텍스트/마크다운/코드블록 금지.
형식:
{
  "conflicts": boolean,
  "explanation": "이유",
  "recommendation": "replace_old" | "keep_both" | "keep_old"
}

recommendation 가이드:
- replace_old: 신규가 기존을 명확히 대체(방향 변경)하는 경우
- keep_old: 신규가 기존과 충돌하지만, 신규가 애매/신뢰 낮아 보이는 경우
- keep_both: 시점/맥락에 따라 병기하는 편이 안전한 경우
"""

    response_schema = {
        "type": "object",
        "properties": {
            "conflicts": {"type": "boolean"},
            "explanation": {"type": "string"},
            "recommendation": {
                "type": "string",
                "enum": ["replace_old", "keep_both", "keep_old"],
            },
        },
        "required": ["conflicts", "explanation", "recommendation"],
    }

    test_pairs = [
        {
            "name": "conflict",
            "existing": "키위포 제외",
            "new": "키위포 서브로 노출",
            "expected_conflicts": True,
        },
        {
            "name": "no_conflict",
            "existing": "헤더 볼드체",
            "new": "본문 세리프체",
            "expected_conflicts": False,
        },
    ]

    for pair in test_pairs:
        contents = (
            "아래 두 항목이 충돌하는지 판정해.\n\n"
            f"[기존]\n{pair['existing']}\n\n"
            f"[신규]\n{pair['new']}\n"
        )

        response = client.models.generate_content(
            model=MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=response_schema,
            ),
        )

        result = json.loads(response.text)

        print(f"\n=== {pair['name']} ===")
        print("EXISTING:", pair["existing"])
        print("NEW     :", pair["new"])
        print("OUTPUT  :", json.dumps(result, ensure_ascii=False, indent=2))
        print("EXPECTED conflicts:", pair["expected_conflicts"])


if __name__ == "__main__":
    main()

