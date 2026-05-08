from __future__ import annotations

import sys
from pathlib import Path

# python db/seed_history.py 로 실행해도 imports가 동작하도록 프로젝트 루트를 sys.path에 추가
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv()

from db.database import init_db, insert_history  # noqa: E402
from services.gemini_service import refine_feedback  # noqa: E402


def _split_blocks(md_text: str) -> list[str]:
    """
    '## ' 헤더 기준으로 블록 분리.
    첫 번째가 헤더가 아니면 버림.
    """
    import re

    parts = re.split(r"(?m)^##\s+", md_text)
    if not parts:
        return []
    blocks: list[str] = []
    for p in parts[1:]:
        p = p.strip()
        if not p:
            continue
        blocks.append("## " + p)
    return blocks


def seed_history_from_md(md_path: Path) -> None:
    init_db()

    md_text = md_path.read_text(encoding="utf-8")
    blocks = _split_blocks(md_text)
    if not blocks:
        raise RuntimeError("No '## ' blocks found in markdown")

    inserted = 0
    for block in blocks:
        # Slack 경로와 동일하게: 항상 LLM 정제 → scope/type 정규화 보장
        refined = refine_feedback(block)
        insert_history(
            {
                "date": refined.date,
                "topic": refined.topic,
                "summary": refined.summary,
                "scope": refined.scope,
                "type": refined.type,
                "category": refined.category,
                "original_quote": refined.original_quote,
                "full_text": block,
                "status": "활성",
            }
        )
        inserted += 1

    print(f"seed_history complete: inserted {inserted} blocks from {md_path}")


if __name__ == "__main__":
    default_md = PROJECT_ROOT / "db" / "history.md"
    md_path = Path(sys.argv[1]) if len(sys.argv) >= 2 else default_md
    if not md_path.exists():
        raise SystemExit(
            f"history markdown not found: {md_path}\n"
            f"Usage: python db/seed_history.py [path-to-markdown.md]"
        )
    seed_history_from_md(md_path)

