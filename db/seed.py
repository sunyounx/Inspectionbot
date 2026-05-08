from __future__ import annotations

import sys
from pathlib import Path

# python db/seed.py 로 실행해도 imports가 동작하도록 프로젝트 루트를 sys.path에 추가
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv()

from db.database import _connect, init_db  # noqa: E402


GUIDELINES: list[tuple[str, str]] = [
    # 이미지 체크리스트 (5)
    (
        "이미지/퍼플 5% 룰",
        "올더뮤 퍼플(#3D1C5C)은 화면 약 5% 이내 포인트 사용 권장(스틱 띠/CTA 배지/패키지 디테일 등). 배경 전체를 퍼플로 채우면 범용 이너뷰티 느낌이 날 수 있음.",
    ),
    (
        "이미지/소지품 3개 법칙",
        "인물 주변 소지품은 3개 이내 권장. 여백이 품격(Quiet Bold). 예: 커피+노트북+스틱 / 거울+파우치+스틱.",
    ),
    (
        "이미지/5대 허용 공간",
        "오피스·카페·세면대(거울)·차 안·비행기. 공통 맥락: '프로페셔널이 자기 기준을 지키는 순간'에 해당하는 공간 지향.",
    ),
    (
        "이미지/배경 톤",
        "뉴트럴 배경 지향. 단, 영상은 기존 배경 유지(크로마키 불필요). 이미지 DA는 신규 제작분부터 뉴트럴 적용, 기존 이미지는 억지 교체 X.",
    ),
    (
        "이미지/키위 노출",
        "딥글로우 보라 박스=MAIN, 자두포 1~2개=서브 노출. 키위포는 제외.",
    ),
    # 카피 체크리스트 (3)
    (
        "카피/톤앤매너",
        "Knowledge의 광고주 톤앤매너 및 과거 피드백을 기준으로, 딱딱한 지적이 아니라 확인 질문+제안 형태로 조정 포인트를 제시.",
    ),
    (
        "카피/워딩 수위·과장 표현",
        "워딩 수위/과장 표현/선호·비선호 표현을 확인하고, 소비자 오인 소지가 있으면 완화(개인차/근거) 표현을 제안.",
    ),
    (
        "카피/카피 워싱",
        "카피의 톤을 광고주 선호 방향으로 순화하는 작업(표현 수위·직설/과장 완화, 차분한 톤으로 정리) 필요 여부 판단.",
    ),
]


TERMS: list[tuple[str, str, str]] = [
    (
        "Quiet Bold",
        "여백이 품격. 적을수록 고급스럽다는 올더뮤의 비주얼 철학(소지품/요소를 절제하고 핵심만 남김).",
        "내부 가이드",
    ),
    (
        "퍼플 5% 룰",
        "올더뮤 퍼플(#3D1C5C)을 화면의 약 5% 이내로 포인트 사용하라는 방향성 가이드.",
        "내부 가이드",
    ),
    (
        "카피 워싱",
        "카피의 톤을 광고주 선호 방향으로 순화하는 작업(직설/과장 완화, 차분한 톤 유지).",
        "내부 가이드",
    ),
    (
        "CG-03 구도",
        "Knowledge 문서에 정의된 특정 구도/레이아웃 규칙을 지칭(세부는 Knowledge 참조).",
        "Knowledge",
    ),
]


def seed() -> None:
    init_db()

    with _connect() as conn:
        with conn.cursor() as cur:
            # guideline: (category, content) 중복 방지용으로 존재 체크 후 insert
            inserted_guidelines = 0
            for category, content in GUIDELINES:
                cur.execute(
                    "SELECT 1 FROM guideline WHERE category = %s AND content = %s LIMIT 1",
                    (category, content),
                )
                if cur.fetchone():
                    continue
                cur.execute(
                    "INSERT INTO guideline (category, content) VALUES (%s, %s)",
                    (category, content),
                )
                inserted_guidelines += 1

            # terms: UNIQUE(term) 기반 upsert
            inserted_terms = 0
            for term, definition, source in TERMS:
                cur.execute(
                    """
                    INSERT INTO terms (term, definition, source)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (term) DO UPDATE SET
                      definition = EXCLUDED.definition,
                      source = EXCLUDED.source
                    """,
                    (term, definition, source),
                )
                inserted_terms += 1

        conn.commit()
        print(f"seed complete: guideline +{inserted_guidelines}, terms upsert {inserted_terms}")


if __name__ == "__main__":
    seed()

