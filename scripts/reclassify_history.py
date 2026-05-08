"""일회성: category가 NULL이거나 기본값 '크리에이티브'인 history 행을 Gemini로 재분류.

사용:
  DATABASE_URL="..." python scripts/reclassify_history.py

또는 프로젝트 루트에서 .env 로드 후:
  python scripts/reclassify_history.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv()

from db.database import _connect, _fetchall  # noqa: E402
from google.genai import types  # noqa: E402
from services.gemini_service import MODEL, client  # noqa: E402

CATEGORIES = {"크리에이티브", "프로모션", "CRM", "브랜딩", "퍼포먼스", "기타"}
_CATEGORY_ENUM = ["크리에이티브", "프로모션", "CRM", "브랜딩", "퍼포먼스", "기타"]

_MAX_TEXT_CHARS = 12000


def classify_category(text: str) -> str:
    """텍스트만 보고 category만 반환 (refine 전체 호출 없음)."""
    response_schema = {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": _CATEGORY_ENUM},
        },
        "required": ["category"],
    }
    system_instruction = (
        "아래 피드백 텍스트를 다음 중 정확히 하나의 카테고리로만 분류하세요: "
        "크리에이티브, 프로모션, CRM, 브랜딩, 퍼포먼스, 기타."
    )
    body = (text or "").strip()
    if len(body) > _MAX_TEXT_CHARS:
        body = body[:_MAX_TEXT_CHARS]
    user_content = f"아래 피드백을 분류하세요.\n\n---\n{body}\n---"

    resp = client.models.generate_content(
        model=MODEL,
        contents=user_content,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=response_schema,
        ),
    )
    raw = (resp.text or "").strip()
    data = json.loads(raw)
    cat = (data.get("category") or "").strip()
    if cat not in CATEGORIES:
        return "기타"
    return cat


def load_candidates() -> list[dict]:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM history
                WHERE category IS NULL OR category = %s
                ORDER BY id ASC
                """,
                ("크리에이티브",),
            )
            return _fetchall(cur)


def main() -> None:
    items = load_candidates()
    total = len(items)
    print(f"총 {total}건 재분류 (category IS NULL 또는 '크리에이티브')")

    with _connect() as conn:
        for i, item in enumerate(items, 1):
            hid = item.get("id")
            text = (item.get("summary") or item.get("full_text") or "") or ""
            topic = (item.get("topic") or "").strip().replace("\n", " ")
            if len(topic) > 80:
                topic = topic[:77] + "..."

            if not str(text).strip():
                print(f"{i}/{total} #{hid} — 텍스트 없음, 스킵")
                continue

            try:
                category = classify_category(text)
            except Exception as e:
                print(f"{i}/{total} #{hid} — 오류 ({e!r}), 스킵")
                continue

            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE history SET category = %s WHERE id = %s",
                        (category, hid),
                    )
                conn.commit()
            except Exception as e:
                print(f"{i}/{total} #{hid} — DB 오류 ({e!r}), 스킵")
                continue

            print(f"{i}/{total} #{hid} {topic} → {category}")

    print("done")


if __name__ == "__main__":
    main()
