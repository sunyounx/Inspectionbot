"""일회성: slack_raw_messages / pending_approvals / history 텍스트에 clean_slack_markup 적용."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv()

from db.database import _connect  # noqa: E402
from services.slack_service import clean_slack_markup  # noqa: E402


def main() -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            for table, col in [
                ("slack_raw_messages", "text"),
                ("pending_approvals", "full_text"),
                ("history", "full_text"),
            ]:
                cur.execute(f"SELECT id, {col} FROM {table} WHERE {col} IS NOT NULL AND {col} != ''")
                rows = cur.fetchall()
                n = 0
                for r in rows:
                    old = r[col]
                    new = clean_slack_markup(old)
                    if new != old:
                        cur.execute(
                            f"UPDATE {table} SET {col} = %s WHERE id = %s",
                            (new, r["id"]),
                        )
                        n += 1
                print(f"{table}.{col}: updated {n} rows (scanned {len(rows)})")
        conn.commit()
    print("done")


if __name__ == "__main__":
    main()
