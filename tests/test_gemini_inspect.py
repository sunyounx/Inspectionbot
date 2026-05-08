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

    system_prompt = """당신은 광고 소재 검수봇입니다.
아래 히스토리 규칙을 기준으로 소재를 검수하세요.

## 활성 히스토리
1. [퍼플 비중] 배경에 퍼플 톤 비중을 30% 이상으로(또는 올더뮤 퍼플을 포인트로) 사용 (적용: 이미지DA)
2. [CTA 톤] '지금 바로' 같은 직접적인 CTA는 피하고 차분한 톤을 유지 (적용: 카피)
3. [키위포] 키위포는 메인에는 제외하고 서브 컷에서만 자연스럽게 노출 (적용: 전체)
4. [텍스트 크기] 텍스트는 너무 작지 않게 가독성 확보 (적용: 전체)

검수 방식:
- 각 규칙에 대해 준수/위반/해당없음을 판정
- 위반/확인필요라면 구체적으로 어떻게 바꾸면 좋을지 제안
- 반드시 규칙 번호(예: 1, 2, 3...)를 인용해서 근거를 명시
"""

    user_message = """다음 카피를 검수해줘:

지금 바로 시작하세요!
올더뮤 딥글로우로 3일만에 피부가 확 달라집니다.
"""

    response = client.models.generate_content(
        model=MODEL,
        contents=user_message,
        config=types.GenerateContentConfig(system_instruction=system_prompt),
    )

    print("=== INSPECT RESULT ===\n")
    print(response.text)


if __name__ == "__main__":
    main()

