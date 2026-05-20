from __future__ import annotations

from contextlib import contextmanager
from datetime import date as _date
from datetime import datetime
import os
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "db" / "schema.sql"


@contextmanager
def _connect():
    """
    psycopg2 connection context manager that ALWAYS closes connections.
    (psycopg2's native connection __enter__/__exit__ does not close.)
    """
    dsn = (os.getenv("DATABASE_URL") or "").strip()
    if not dsn:
        raise RuntimeError("DATABASE_URL is required (Replit PostgreSQL)")
    conn = psycopg2.connect(dsn, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _exec_schema(conn: psycopg2.extensions.connection, schema_sql: str) -> None:
    # psycopg2에는 sqlite executescript가 없어서 ';' 단위로 실행
    statements = [s.strip() for s in schema_sql.split(";") if s.strip()]
    with conn.cursor() as cur:
        for stmt in statements:
            cur.execute(stmt)


def init_db() -> None:
    """Create tables if they don't exist."""
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with _connect() as conn:
        _exec_schema(conn, schema_sql)
        # 기존 운영 DB에 컬럼 추가(마이그레이션) — CREATE TABLE만으로는 반영되지 않음
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE IF EXISTS pending_approvals ADD COLUMN IF NOT EXISTS source_ts TEXT")
            cur.execute("ALTER TABLE IF EXISTS history ADD COLUMN IF NOT EXISTS source_ts TEXT")
            cur.execute("ALTER TABLE IF EXISTS pending_approvals ADD COLUMN IF NOT EXISTS author_user_id TEXT")
            cur.execute("ALTER TABLE IF EXISTS pending_approvals ADD COLUMN IF NOT EXISTS author_name TEXT")
            cur.execute("ALTER TABLE IF EXISTS pending_approvals ADD COLUMN IF NOT EXISTS message_time TEXT")
            cur.execute("ALTER TABLE IF EXISTS history ADD COLUMN IF NOT EXISTS author_user_id TEXT")
            cur.execute("ALTER TABLE IF EXISTS history ADD COLUMN IF NOT EXISTS author_name TEXT")
            cur.execute("ALTER TABLE IF EXISTS history ADD COLUMN IF NOT EXISTS message_time TEXT")
            cur.execute("ALTER TABLE IF EXISTS slack_raw_messages ADD COLUMN IF NOT EXISTS parent_ts TEXT")
            cur.execute("ALTER TABLE IF EXISTS gdrive_inspections ADD COLUMN IF NOT EXISTS image_ids TEXT")
            cur.execute("ALTER TABLE IF EXISTS gdrive_inspections ADD COLUMN IF NOT EXISTS thumbnail_files TEXT")
            cur.execute("ALTER TABLE IF EXISTS slack_inspections ADD COLUMN IF NOT EXISTS original_text TEXT")
            cur.execute(
                "ALTER TABLE IF EXISTS history ADD COLUMN IF NOT EXISTS category TEXT DEFAULT '크리에이티브'"
            )
            cur.execute(
                "ALTER TABLE IF EXISTS pending_approvals ADD COLUMN IF NOT EXISTS category TEXT DEFAULT '미분류'"
            )
            cur.execute("ALTER TABLE IF EXISTS pending_approvals ADD COLUMN IF NOT EXISTS parent_ts TEXT")
            cur.execute(
                "ALTER TABLE IF EXISTS pending_approvals ADD COLUMN IF NOT EXISTS teams_notified INTEGER NOT NULL DEFAULT 0"
            )
            cur.execute(
                "ALTER TABLE IF EXISTS pending_approvals ADD COLUMN IF NOT EXISTS approved_history_id INTEGER"
            )
            # multi-user gdrive oauth tokens: migrate old table(id=1) → session_id keyed
            cur.execute(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_name='gdrive_oauth_tokens' AND column_name='session_id'
                """
            )
            has_session = cur.fetchone() is not None
            if not has_session:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS gdrive_oauth_tokens_v2 (
                        id SERIAL PRIMARY KEY,
                        session_id TEXT NOT NULL UNIQUE,
                        access_token TEXT NOT NULL,
                        refresh_token TEXT,
                        expires_at TIMESTAMP,
                        user_email TEXT,
                        created_at TIMESTAMP NOT NULL DEFAULT NOW()
                    )
                    """
                )
                # 기존 단일 행이 있으면 legacy 세션으로 이관
                cur.execute(
                    """
                    INSERT INTO gdrive_oauth_tokens_v2 (session_id, access_token, refresh_token, expires_at, user_email)
                    SELECT 'legacy', access_token, refresh_token, expires_at, user_email
                    FROM gdrive_oauth_tokens
                    WHERE access_token IS NOT NULL
                    ON CONFLICT (session_id) DO NOTHING
                    """
                )
                cur.execute("DROP TABLE IF EXISTS gdrive_oauth_tokens")
                cur.execute("ALTER TABLE gdrive_oauth_tokens_v2 RENAME TO gdrive_oauth_tokens")
        conn.commit()


def _normalize_value(v: Any) -> Any:
    # Keep frontend display stable (SQLite used "YYYY-MM-DD HH:MM:SS" strings).
    if isinstance(v, datetime):
        try:
            return v.isoformat(sep=" ", timespec="seconds")
        except Exception:
            return v.isoformat()
    if isinstance(v, _date):
        return v.isoformat()
    return v


def _fetchall(cur) -> list[dict[str, Any]]:
    rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        for k, v in list(d.items()):
            d[k] = _normalize_value(v)
        out.append(d)
    return out


def get_active_history() -> list[dict[str, Any]]:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM history WHERE status = %s ORDER BY id DESC", ("활성",))
            return _fetchall(cur)


def get_history_by_topic(topic: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM history WHERE topic = %s ORDER BY id DESC", (topic,))
            return _fetchall(cur)


def get_history(status: str | None = None, category: str | None = None) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if status:
        where.append("status = %s")
        params.append(status)
    if category:
        where.append("category = %s")
        params.append(category)
    sql = "SELECT * FROM history"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return _fetchall(cur)


def insert_history(item: dict[str, Any]) -> int:
    fields = [
        "date",
        "topic",
        "summary",
        "scope",
        "type",
        "full_text",
        "original_quote",
        "source_ts",
        "author_user_id",
        "author_name",
        "message_time",
        "status",
        "changed_date",
        "slack_link",
        "category",
    ]
    payload = {k: item.get(k) for k in fields if k in item}

    if "status" not in payload or payload["status"] is None:
        payload["status"] = "활성"
    if "category" not in payload or payload.get("category") is None:
        payload["category"] = "미분류"

    with _connect() as conn:
        columns = ", ".join(payload.keys())
        placeholders = ", ".join(["%s"] * len(payload))
        values = list(payload.values())
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO history ({columns}) VALUES ({placeholders}) RETURNING id",
                values,
            )
            new_id = int(cur.fetchone()["id"])
        conn.commit()
        return new_id


def update_history_status(id: int, status: str, changed_date: str) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE history SET status = %s, changed_date = %s WHERE id = %s",
                (status, changed_date, id),
            )
        conn.commit()


_HISTORY_UPDATABLE = frozenset({"topic", "summary", "scope", "type", "full_text", "original_quote", "category"})


def update_history(id: int, fields: dict[str, Any]) -> bool:
    """topic, summary, scope, type, full_text, original_quote 만 반영. rowcount>0 이면 True."""
    filtered = {k: fields[k] for k in fields if k in _HISTORY_UPDATABLE}
    if not filtered:
        return False
    with _connect() as conn:
        sets = ", ".join(f"{k} = %s" for k in filtered)
        values = list(filtered.values()) + [id]
        with conn.cursor() as cur:
            cur.execute(f"UPDATE history SET {sets} WHERE id = %s", values)
            ok = cur.rowcount > 0
        conn.commit()
        return ok


def delete_history(id: int) -> bool:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM history WHERE id = %s", (id,))
            ok = cur.rowcount > 0
        conn.commit()
        return ok


def get_guidelines() -> list[dict[str, Any]]:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM guideline ORDER BY id ASC")
            return _fetchall(cur)


def get_terms() -> list[dict[str, Any]]:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM terms ORDER BY id ASC")
            return _fetchall(cur)


def insert_copybank(item: dict[str, Any]) -> int:
    fields = ["category", "target", "copy_text", "tags", "source"]
    payload = {k: item.get(k) for k in fields if k in item}
    if not (payload.get("copy_text") or "").strip():
        raise ValueError("copy_text is required")
    with _connect() as conn:
        columns = ", ".join(payload.keys())
        placeholders = ", ".join(["%s"] * len(payload))
        values = list(payload.values())
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO copybank ({columns}) VALUES ({placeholders}) RETURNING id",
                values,
            )
            new_id = int(cur.fetchone()["id"])
        conn.commit()
        return new_id


def get_copybank(limit: int = 200) -> list[dict[str, Any]]:
    n = min(max(int(limit or 200), 1), 1000)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM copybank ORDER BY id DESC LIMIT %s", (n,))
            return _fetchall(cur)


def delete_copybank(id: int) -> bool:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM copybank WHERE id = %s", (int(id),))
            ok = cur.rowcount > 0
        conn.commit()
        return ok


def insert_pending_approval(item: dict[str, Any]) -> int:
    fields = [
        "date",
        "topic",
        "summary",
        "scope",
        "type",
        "full_text",
        "original_quote",
        "slack_link",
        "source_ts",
        "author_user_id",
        "author_name",
        "message_time",
        "has_conflict",
        "conflict_explanation",
        "conflict_recommendation",
        "conflict_old_history_id",
        "status",
        "category",
        "parent_ts",
        "teams_notified",
    ]
    payload = {k: item.get(k) for k in fields if k in item}
    if "status" not in payload or payload["status"] is None:
        payload["status"] = "대기중"
    if "category" not in payload or payload.get("category") is None:
        payload["category"] = "크리에이티브"
    if "teams_notified" not in payload or payload.get("teams_notified") is None:
        payload["teams_notified"] = 0

    with _connect() as conn:
        columns = ", ".join(payload.keys())
        placeholders = ", ".join(["%s"] * len(payload))
        values = list(payload.values())
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO pending_approvals ({columns}) VALUES ({placeholders}) RETURNING id",
                values,
            )
            new_id = int(cur.fetchone()["id"])
        conn.commit()
        return new_id


def get_pending_approvals(status: str = "대기중") -> list[dict[str, Any]]:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM pending_approvals WHERE status = %s ORDER BY id DESC",
                (status,),
            )
            return _fetchall(cur)


def _pending_admin_where(
    status: str | None,
    q: str | None,
    author: str | None,
) -> tuple[str, list[Any]]:
    where: list[str] = []
    params: list[Any] = []
    st = (status or "").strip()
    if st:
        where.append("status = %s")
        params.append(st)
    else:
        where.append("status IN (%s, %s)")
        params.extend(["대기중", "처리중"])
    qn = (q or "").strip()
    if qn:
        where.append("full_text ILIKE %s")
        params.append(f"%{qn}%")
    an = (author or "").strip()
    if an:
        where.append("(author_user_id = %s OR author_name ILIKE %s)")
        params.extend([an, f"%{an}%"])
    return " AND ".join(where), params


def get_pending_approvals_for_admin(
    limit: int = 100,
    offset: int = 0,
    status: str | None = None,
    q: str | None = None,
    author: str | None = None,
    order: str = "desc",
) -> list[dict[str, Any]]:
    """슬랙 관리 탭: 필터·페이지네이션. status 생략·빈값 → 대기중+처리중."""
    lim = min(max(int(limit or 100), 1), 500)
    off = max(int(offset or 0), 0)
    where_sql, params = _pending_admin_where(status, q, author)
    dir_sql = "ASC" if (order or "desc").lower() == "asc" else "DESC"
    sql = f"""
        SELECT * FROM pending_approvals
        WHERE {where_sql}
        ORDER BY
          message_time {dir_sql} NULLS LAST,
          id {dir_sql}
        LIMIT %s OFFSET %s
    """
    exec_params = list(params)
    exec_params.extend([lim, off])
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, exec_params)
            return _fetchall(cur)


def count_pending_approvals_for_admin(
    status: str | None = None,
    q: str | None = None,
    author: str | None = None,
) -> int:
    where_sql, params = _pending_admin_where(status, q, author)
    sql = f"SELECT COUNT(*)::int AS n FROM pending_approvals WHERE {where_sql}"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, list(params))
            row = cur.fetchone()
            return int((row or {}).get("n") or 0)


def get_pending_approval_by_id(id: int) -> dict[str, Any] | None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM pending_approvals WHERE id = %s", (id,))
            row = cur.fetchone()
            return dict(row) if row else None


def has_open_pending_for_source_ts(source_ts: str) -> bool:
    """동일 source_ts로 대기·처리중 pending이 이미 있으면 True (중복 insert 방지)."""
    st = (source_ts or "").strip()
    if not st:
        return False
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM pending_approvals
                WHERE source_ts = %s AND status IN (%s, %s)
                LIMIT 1
                """,
                (st, "대기중", "처리중"),
            )
            return cur.fetchone() is not None


def pending_source_ts_ever_seen(source_ts: str) -> bool:
    """동일 source_ts가 어떤 상태(승인/폐기/흡수 포함)로든 한 번이라도 적재됐으면 True.
    Figma 댓글 폴링에서 동일 댓글 재적재 방지 용도."""
    st = (source_ts or "").strip()
    if not st:
        return False
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pending_approvals WHERE source_ts = %s LIMIT 1",
                (st,),
            )
            return cur.fetchone() is not None


def get_latest_pending_for_source_ts(source_ts: str) -> dict[str, Any] | None:
    """동일 source_ts의 가장 최근 pending(상태 무관). Figma 폴링이 동일 스레드 재insert를 피하기 위해
    기존 pending의 full_text와 현재 full_text를 비교하는 데 사용."""
    st = (source_ts or "").strip()
    if not st:
        return None
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM pending_approvals WHERE source_ts = %s ORDER BY id DESC LIMIT 1",
                (st,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def insert_figma_comment_image(
    *,
    file_key: str,
    comment_id: str,
    node_id: str | None,
    file_name: str | None,
    mime_type: str,
    image_data: bytes,
) -> None:
    fk = (file_key or "").strip()
    cid = (comment_id or "").strip()
    if not fk or not cid or not image_data:
        return
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO figma_comment_images
                (file_key, comment_id, node_id, file_name, mime_type, image_data)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (file_key, comment_id) DO NOTHING
                """,
                (fk, cid, node_id, file_name, mime_type or "image/png", image_data),
            )
        conn.commit()


def get_figma_comment_image(file_key: str, comment_id: str) -> dict[str, Any] | None:
    fk = (file_key or "").strip()
    cid = (comment_id or "").strip()
    if not fk or not cid:
        return None
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM figma_comment_images WHERE file_key = %s AND comment_id = %s LIMIT 1",
                (fk, cid),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def update_pending_status(id: int, status: str) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE pending_approvals SET status = %s WHERE id = %s", (status, id))
        conn.commit()


def update_pending_approved(id: int, history_id: int) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE pending_approvals SET status = %s, approved_history_id = %s WHERE id = %s",
                ("승인됨", int(history_id), int(id)),
            )
        conn.commit()


def cancel_pending_approval(id: int) -> dict[str, Any]:
    """승인됨 pending을 대기중으로 되돌리고, 연결된 히스토리를 삭제한다. use_new 시 변경됨→활성 복구."""
    today = _date.today().isoformat()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM pending_approvals WHERE id = %s", (int(id),))
            row = cur.fetchone()
            if not row:
                return {"ok": False, "reason": "not_found"}
            pending = dict(row)
            if (pending.get("status") or "").strip() != "승인됨":
                return {"ok": False, "reason": "not_approved", "status": pending.get("status")}

            history_id = pending.get("approved_history_id")
            if history_id is None:
                sts = (pending.get("source_ts") or "").strip()
                if sts:
                    cur.execute(
                        "SELECT id FROM history WHERE source_ts = %s ORDER BY id DESC LIMIT 1",
                        (sts,),
                    )
                    found = cur.fetchone()
                    if found:
                        history_id = int(found["id"])

            deleted_history_id: int | None = None
            if history_id is not None:
                cur.execute("DELETE FROM history WHERE id = %s", (int(history_id),))
                if cur.rowcount > 0:
                    deleted_history_id = int(history_id)

            restored_old_history_id: int | None = None
            old_id = pending.get("conflict_old_history_id")
            if old_id is not None:
                cur.execute("SELECT status FROM history WHERE id = %s", (int(old_id),))
                old_row = cur.fetchone()
                if old_row and (old_row.get("status") or "").strip() == "변경됨":
                    cur.execute(
                        "UPDATE history SET status = %s, changed_date = %s WHERE id = %s",
                        ("활성", today, int(old_id)),
                    )
                    restored_old_history_id = int(old_id)

            cur.execute(
                "UPDATE pending_approvals SET status = %s, approved_history_id = NULL WHERE id = %s",
                ("대기중", int(id)),
            )
        conn.commit()

    return {
        "ok": True,
        "pending_status": "대기중",
        "deleted_history_id": deleted_history_id,
        "restored_old_history_id": restored_old_history_id,
    }


def update_pending_teams_notified(id: int, notified: bool) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE pending_approvals SET teams_notified = %s WHERE id = %s",
                (1 if notified else 0, int(id)),
            )
        conn.commit()


def insert_raw_message(item: dict[str, Any]) -> None:
    """ts UNIQUE — 중복이면 ON CONFLICT DO NOTHING."""
    ts = (item.get("ts") or "").strip()
    if not ts:
        return
    parent_ts = item.get("parent_ts")
    if parent_ts is not None:
        parent_ts = str(parent_ts).strip() or None
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO slack_raw_messages
                (ts, channel, user_id, text, is_bot, is_feedback, slack_link, parent_ts)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ts) DO NOTHING
                """,
                (
                    ts,
                    item.get("channel") or "",
                    item.get("user_id"),
                    item.get("text"),
                    1 if item.get("is_bot") else 0,
                    None,
                    item.get("slack_link"),
                    parent_ts,
                ),
            )
        conn.commit()


def update_raw_message_feedback(ts: str, is_feedback: int) -> None:
    if not ts:
        return
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE slack_raw_messages SET is_feedback = %s WHERE ts = %s",
                (is_feedback, ts),
            )
        conn.commit()


def get_raw_messages(
    limit: int = 100,
    offset: int = 0,
    filter_kind: str | None = None,
    q: str | None = None,
    author: str | None = None,
    has_files: bool | None = None,
    order: str = "desc",
) -> list[dict[str, Any]]:
    """최상위 메시지(parent_ts IS NULL)만. reply_count는 스레드 댓글 수."""
    where: list[str] = ["m.parent_ts IS NULL"]
    params: list[Any] = []
    if filter_kind == "bot":
        where.append("m.is_bot = 1")
    elif filter_kind == "feedback":
        where.append("m.is_feedback = 1")
    elif filter_kind == "not_feedback":
        where.append("m.is_feedback = 0")

    qn = (q or "").strip()
    if qn:
        where.append("m.text ILIKE %s")
        params.append(f"%{qn}%")

    an = (author or "").strip()
    if an:
        where.append("m.user_id = %s")
        params.append(an)

    if has_files is True:
        where.append(
            "EXISTS (SELECT 1 FROM message_files f WHERE f.message_ts = m.ts)"
        )
    elif has_files is False:
        where.append(
            "NOT EXISTS (SELECT 1 FROM message_files f WHERE f.message_ts = m.ts)"
        )

    order_dir = "ASC" if (order or "desc").strip().lower() == "asc" else "DESC"

    sql = """
        SELECT m.*,
            COALESCE(
                (SELECT COUNT(*)::int FROM slack_raw_messages c WHERE c.parent_ts = m.ts),
                0
            ) AS reply_count
        FROM slack_raw_messages m
        WHERE """ + " AND ".join(where)
    sql += f" ORDER BY CAST(m.ts AS DOUBLE PRECISION) {order_dir} LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return _fetchall(cur)


def get_raw_message_by_ts(ts: str) -> dict[str, Any] | None:
    ts = (ts or "").strip()
    if not ts:
        return None
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM slack_raw_messages WHERE ts = %s", (ts,))
            row = cur.fetchone()
            return dict(row) if row else None


def slack_raw_message_ts_exists(ts: str) -> bool:
    ts = (ts or "").strip()
    if not ts:
        return False
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM slack_raw_messages WHERE ts = %s LIMIT 1", (ts,))
            return cur.fetchone() is not None


def get_top_level_raw_since(ts_floor: float) -> list[dict[str, Any]]:
    """parent_ts IS NULL 이고 ts >= ts_floor 인 최상위 Slack 메시지.
    figma 댓글용 가짜 ts(`figma:...`)는 CAST에서 깨지므로 channel로 제외."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ts FROM slack_raw_messages
                WHERE parent_ts IS NULL
                  AND channel NOT LIKE 'figma:%%'
                  AND CAST(ts AS DOUBLE PRECISION) >= %s
                ORDER BY CAST(ts AS DOUBLE PRECISION) ASC
                """,
                (float(ts_floor),),
            )
            return _fetchall(cur)


def get_raw_thread_replies_bulk(parent_ts_list: list[str]) -> dict[str, list[dict[str, Any]]]:
    cleaned = [str(x).strip() for x in parent_ts_list if str(x).strip()]
    if not cleaned:
        return {}
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM slack_raw_messages
                WHERE parent_ts = ANY(%s)
                  AND channel NOT LIKE 'figma:%%'
                ORDER BY parent_ts, CAST(ts AS DOUBLE PRECISION) ASC
                """,
                (cleaned,),
            )
            rows = _fetchall(cur)
    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        p = (r.get("parent_ts") or "").strip()
        if not p:
            continue
        out.setdefault(p, []).append(r)
    return out


def absorb_parent_pending_if_any(parent_ts: str) -> None:
    pt = (parent_ts or "").strip()
    if not pt:
        return
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE pending_approvals
                SET status = %s
                WHERE source_ts = %s
                  AND parent_ts IS NULL
                  AND status = %s
                """,
                ("흡수됨", pt, "대기중"),
            )
        conn.commit()


def absorb_open_pendings_for_thread(parent_ts: str) -> None:
    """스레드(부모 + 모든 댓글)에 속한 '대기중' pending을 모두 '흡수됨'으로 변경.
    같은 스레드의 새 댓글이 들어와 누적 full_text로 신규 pending을 적재하기 직전에 호출."""
    pt = (parent_ts or "").strip()
    if not pt:
        return
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE pending_approvals
                SET status = %s
                WHERE status = %s
                  AND (
                    (source_ts = %s AND parent_ts IS NULL)
                    OR parent_ts = %s
                  )
                """,
                ("흡수됨", "대기중", pt, pt),
            )
        conn.commit()


def get_raw_thread_replies(parent_ts: str) -> list[dict[str, Any]]:
    parent_ts = (parent_ts or "").strip()
    if not parent_ts:
        return []
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM slack_raw_messages
                WHERE parent_ts = %s
                  AND channel NOT LIKE 'figma:%%'
                ORDER BY CAST(ts AS DOUBLE PRECISION) ASC
                """,
                (parent_ts,),
            )
            return _fetchall(cur)


def get_poll_state(key: str) -> str | None:
    if not key:
        return None
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM poll_state WHERE key = %s", (key,))
            row = cur.fetchone()
            return (row or {}).get("value")


def set_poll_state(key: str, value: str) -> None:
    if not key:
        return
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO poll_state (key, value)
                VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                (key, value),
            )
        conn.commit()


def insert_message_file(item: dict[str, Any]) -> None:
    """
    message_ts + url UNIQUE — 중복이면 ON CONFLICT DO NOTHING.
    item은 최소 message_ts, url을 포함해야 합니다.
    """
    message_ts = (item.get("message_ts") or "").strip()
    url = (item.get("url") or "").strip()
    if not message_ts or not url:
        return

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO message_files
                (message_ts, file_id, name, filetype, mimetype, url, is_external, external_type, size)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (message_ts, url) DO NOTHING
                """,
                (
                    message_ts,
                    item.get("file_id"),
                    item.get("name"),
                    item.get("filetype"),
                    item.get("mimetype"),
                    url,
                    bool(item.get("is_external")) if item.get("is_external") is not None else False,
                    item.get("external_type"),
                    item.get("size"),
                ),
            )
        conn.commit()


def get_files_by_message_ts(ts: str) -> list[dict[str, Any]]:
    ts = (ts or "").strip()
    if not ts:
        return []
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM message_files
                WHERE message_ts = %s
                ORDER BY id ASC
                """,
                (ts,),
            )
            return _fetchall(cur)


def get_recent_files(limit: int = 50) -> list[dict[str, Any]]:
    limit = int(limit or 50)
    limit = min(max(limit, 1), 500)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM message_files
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (limit,),
            )
            return _fetchall(cur)


def get_files_by_ts_list(ts_list: list[str]) -> dict[str, list[dict[str, Any]]]:
    """
    message_ts IN (...) 를 한 번에 조회해 {ts: [files...]} 형태로 반환.
    빈 리스트면 {} 반환 (IN () SQL 에러 방지).
    """
    if not ts_list:
        return {}
    cleaned = [str(x).strip() for x in ts_list if str(x).strip()]
    if not cleaned:
        return {}

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM message_files
                WHERE message_ts = ANY(%s)
                ORDER BY message_ts ASC, id ASC
                """,
                (cleaned,),
            )
            rows = _fetchall(cur)

    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        ts = str(r.get("message_ts") or "").strip()
        if not ts:
            continue
        out.setdefault(ts, []).append(r)
    return out


def insert_gdrive_inspection(item: dict[str, Any]) -> int:
    fields = [
        "folder_id",
        "folder_name",
        "file_names",
        "image_ids",
        "thumbnail_files",
        "file_count",
        "feedback",
        "rules_checked",
        "drive_url",
        "notified_teams",
    ]
    payload = {k: item.get(k) for k in fields if k in item}
    if not payload.get("folder_id"):
        raise ValueError("folder_id is required")

    with _connect() as conn:
        columns = ", ".join(payload.keys())
        placeholders = ", ".join(["%s"] * len(payload))
        values = list(payload.values())
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO gdrive_inspections ({columns}) VALUES ({placeholders}) RETURNING id",
                values,
            )
            new_id = int(cur.fetchone()["id"])
        conn.commit()
        return new_id


def update_gdrive_inspection_notified(id: int, notified_teams: bool) -> bool:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE gdrive_inspections SET notified_teams = %s WHERE id = %s",
                (bool(notified_teams), int(id)),
            )
            ok = cur.rowcount > 0
        conn.commit()
        return ok


def get_gdrive_inspections(limit: int = 20) -> list[dict[str, Any]]:
    limit = int(limit or 20)
    limit = min(max(limit, 1), 200)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM gdrive_inspections ORDER BY id DESC LIMIT %s", (limit,))
            return _fetchall(cur)


def get_gdrive_inspection_by_id(id: int) -> dict[str, Any] | None:
    try:
        iid = int(id)
    except Exception:
        return None
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM gdrive_inspections WHERE id = %s", (iid,))
            row = cur.fetchone()
            return dict(row) if row else None


def add_saved_folder(item: dict[str, Any]) -> int:
    folder_id = (item.get("folder_id") or "").strip()
    if not folder_id:
        raise ValueError("folder_id is required")
    folder_name = item.get("folder_name")
    drive_url = item.get("drive_url")

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO gdrive_saved_folders (folder_id, folder_name, drive_url)
                VALUES (%s, %s, %s)
                ON CONFLICT (folder_id) DO UPDATE
                SET folder_name = EXCLUDED.folder_name,
                    drive_url = EXCLUDED.drive_url
                RETURNING id
                """,
                (folder_id, folder_name, drive_url),
            )
            new_id = int(cur.fetchone()["id"])
        conn.commit()
        return new_id


def remove_saved_folder(id: int) -> bool:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM gdrive_saved_folders WHERE id = %s", (int(id),))
            ok = cur.rowcount > 0
        conn.commit()
        return ok


def get_saved_folders(limit: int = 50) -> list[dict[str, Any]]:
    limit = int(limit or 50)
    limit = min(max(limit, 1), 200)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM gdrive_saved_folders ORDER BY id DESC LIMIT %s", (limit,))
            return _fetchall(cur)


def upsert_gdrive_oauth_token(
    session_id: str,
    access_token: str,
    refresh_token: str | None,
    expires_at: datetime | None,
    user_email: str | None,
) -> int:
    session_id = (session_id or "").strip()
    if not session_id:
        raise ValueError("session_id is required")
    access_token = (access_token or "").strip()
    if not access_token:
        raise ValueError("access_token is required")

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO gdrive_oauth_tokens (session_id, access_token, refresh_token, expires_at, user_email)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (session_id) DO UPDATE
                SET access_token = EXCLUDED.access_token,
                    refresh_token = COALESCE(EXCLUDED.refresh_token, gdrive_oauth_tokens.refresh_token),
                    expires_at = EXCLUDED.expires_at,
                    user_email = EXCLUDED.user_email
                RETURNING id
                """,
                (session_id, access_token, refresh_token, expires_at, user_email),
            )
            row_id = int(cur.fetchone()["id"])
        conn.commit()
        return row_id


def get_gdrive_oauth_token(session_id: str) -> dict[str, Any] | None:
    session_id = (session_id or "").strip()
    if not session_id:
        return None
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM gdrive_oauth_tokens WHERE session_id = %s ORDER BY id DESC LIMIT 1", (session_id,))
            row = cur.fetchone()
            return dict(row) if row else None


def clear_gdrive_oauth_token(session_id: str) -> None:
    session_id = (session_id or "").strip()
    if not session_id:
        return
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM gdrive_oauth_tokens WHERE session_id = %s", (session_id,))
        conn.commit()


def insert_inspection_thumbnail(
    inspection_id: int,
    image_index: int,
    file_id: str | None,
    file_name: str | None,
    mime_type: str,
    image_data: bytes,
) -> int:
    if not image_data:
        raise ValueError("image_data is required")
    mt = (mime_type or "image/jpeg").strip() or "image/jpeg"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO inspection_thumbnails
                (inspection_id, image_index, file_id, file_name, mime_type, image_data)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (inspection_id, image_index)
                DO UPDATE SET
                    file_id = EXCLUDED.file_id,
                    file_name = EXCLUDED.file_name,
                    mime_type = EXCLUDED.mime_type,
                    image_data = EXCLUDED.image_data
                RETURNING id
                """,
                (
                    int(inspection_id),
                    int(image_index),
                    file_id,
                    file_name,
                    mt,
                    image_data,
                ),
            )
            new_id = int(cur.fetchone()["id"])
        conn.commit()
        return new_id


def get_inspection_thumbnails(inspection_id: int) -> list[dict[str, Any]]:
    """inspection_id에 대한 썸네일 메타(바이너리 제외)."""
    try:
        iid = int(inspection_id)
    except Exception:
        return []
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, inspection_id, image_index, file_id, file_name, mime_type, created_at
                FROM inspection_thumbnails
                WHERE inspection_id = %s
                ORDER BY image_index ASC
                """,
                (iid,),
            )
            return _fetchall(cur)


def get_inspection_thumbnail(inspection_id: int, image_index: int) -> tuple[bytes, str] | None:
    """단일 썸네일 바이트와 mime_type. 없으면 None."""
    try:
        iid = int(inspection_id)
        idx = int(image_index)
    except Exception:
        return None
    if idx < 0:
        return None
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT image_data, mime_type
                FROM inspection_thumbnails
                WHERE inspection_id = %s AND image_index = %s
                """,
                (iid, idx),
            )
            row = cur.fetchone()
            if not row:
                return None
            raw = row.get("image_data")
            if isinstance(raw, memoryview):
                blob = raw.tobytes()
            elif isinstance(raw, bytes):
                blob = raw
            else:
                blob = bytes(raw) if raw is not None else b""
            mt = (row.get("mime_type") or "image/jpeg").strip() or "image/jpeg"
            return (blob, mt)


def insert_slack_inspection(item: dict[str, Any]) -> int:
    fields = ["pending_approval_id", "original_text", "feedback", "rules_checked", "file_count"]
    payload = {k: item.get(k) for k in fields if k in item}
    if "rules_checked" not in payload:
        payload["rules_checked"] = 0
    if "file_count" not in payload:
        payload["file_count"] = 0
    pid = payload.get("pending_approval_id")
    if pid is None:
        raise ValueError("pending_approval_id is required")

    with _connect() as conn:
        columns = ", ".join(payload.keys())
        placeholders = ", ".join(["%s"] * len(payload))
        values = list(payload.values())
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO slack_inspections ({columns}) VALUES ({placeholders}) RETURNING id",
                values,
            )
            new_id = int(cur.fetchone()["id"])
        conn.commit()
        return new_id


def insert_slack_inspection_thumbnail(
    slack_inspection_id: int,
    image_index: int,
    file_id: str | None,
    file_name: str | None,
    mime_type: str,
    image_data: bytes,
) -> int:
    if not image_data:
        raise ValueError("image_data is required")
    mt = (mime_type or "image/jpeg").strip() or "image/jpeg"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO slack_inspection_thumbnails
                (slack_inspection_id, image_index, file_id, file_name, mime_type, image_data)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (slack_inspection_id, image_index)
                DO UPDATE SET
                    file_id = EXCLUDED.file_id,
                    file_name = EXCLUDED.file_name,
                    mime_type = EXCLUDED.mime_type,
                    image_data = EXCLUDED.image_data
                RETURNING id
                """,
                (
                    int(slack_inspection_id),
                    int(image_index),
                    file_id,
                    file_name,
                    mt,
                    image_data,
                ),
            )
            new_id = int(cur.fetchone()["id"])
        conn.commit()
        return new_id


def get_slack_inspection_id_by_pending(pending_approval_id: int) -> int | None:
    try:
        pid = int(pending_approval_id)
    except Exception:
        return None
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM slack_inspections
                WHERE pending_approval_id = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (pid,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return int(row["id"])


def delete_slack_inspection(slack_inspection_id: int) -> None:
    try:
        sid = int(slack_inspection_id)
    except Exception:
        return
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM slack_inspection_thumbnails WHERE slack_inspection_id = %s", (sid,))
            cur.execute("DELETE FROM slack_inspections WHERE id = %s", (sid,))
        conn.commit()


def get_slack_inspection_by_id(id: int) -> dict[str, Any] | None:
    try:
        iid = int(id)
    except Exception:
        return None
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM slack_inspections WHERE id = %s", (iid,))
            row = cur.fetchone()
            return dict(row) if row else None


def get_slack_inspection_thumbnail(slack_inspection_id: int, image_index: int) -> tuple[bytes, str] | None:
    try:
        sid = int(slack_inspection_id)
        idx = int(image_index)
    except Exception:
        return None
    if idx < 0:
        return None
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT image_data, mime_type
                FROM slack_inspection_thumbnails
                WHERE slack_inspection_id = %s AND image_index = %s
                """,
                (sid, idx),
            )
            row = cur.fetchone()
            if not row:
                return None
            raw = row.get("image_data")
            if isinstance(raw, memoryview):
                blob = raw.tobytes()
            elif isinstance(raw, bytes):
                blob = raw
            else:
                blob = bytes(raw) if raw is not None else b""
            mt = (row.get("mime_type") or "image/jpeg").strip() or "image/jpeg"
            return (blob, mt)


def insert_figma_inspection(item: dict[str, Any]) -> int:
    fields = [
        "file_key",
        "file_name",
        "node_id",
        "figma_url",
        "feedback",
        "rules_checked",
        "file_count",
        "notified_teams",
    ]
    payload = {k: item.get(k) for k in fields if k in item}
    if "file_count" not in payload:
        payload["file_count"] = 1
    if "notified_teams" not in payload:
        payload["notified_teams"] = False
    if not payload.get("file_key") or not payload.get("node_id"):
        raise ValueError("file_key and node_id are required")

    with _connect() as conn:
        columns = ", ".join(payload.keys())
        placeholders = ", ".join(["%s"] * len(payload))
        values = list(payload.values())
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO figma_inspections ({columns}) VALUES ({placeholders}) RETURNING id",
                values,
            )
            new_id = int(cur.fetchone()["id"])
        conn.commit()
        return new_id


def insert_figma_inspection_thumbnail(
    figma_inspection_id: int,
    image_index: int,
    file_name: str | None,
    mime_type: str,
    image_data: bytes,
) -> int:
    if not image_data:
        raise ValueError("image_data is required")
    mt = (mime_type or "image/jpeg").strip() or "image/jpeg"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO figma_inspection_thumbnails
                (figma_inspection_id, image_index, file_name, mime_type, image_data)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (figma_inspection_id, image_index)
                DO UPDATE SET
                    file_name = EXCLUDED.file_name,
                    mime_type = EXCLUDED.mime_type,
                    image_data = EXCLUDED.image_data
                RETURNING id
                """,
                (
                    int(figma_inspection_id),
                    int(image_index),
                    file_name,
                    mt,
                    image_data,
                ),
            )
            new_id = int(cur.fetchone()["id"])
        conn.commit()
        return new_id


def get_figma_inspection_by_id(id: int) -> dict[str, Any] | None:
    try:
        iid = int(id)
    except Exception:
        return None
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM figma_inspections WHERE id = %s", (iid,))
            row = cur.fetchone()
            return dict(row) if row else None


def list_figma_inspection_thumbnails_meta(figma_inspection_id: int) -> list[dict[str, Any]]:
    """image_index 순으로 file_name 목록 (딥링크 images 배열용)."""
    try:
        fid = int(figma_inspection_id)
    except Exception:
        return []
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT image_index, file_name
                FROM figma_inspection_thumbnails
                WHERE figma_inspection_id = %s
                ORDER BY image_index ASC
                """,
                (fid,),
            )
            return _fetchall(cur)


def get_figma_inspection_thumbnail(figma_inspection_id: int, image_index: int) -> tuple[bytes, str] | None:
    try:
        fid = int(figma_inspection_id)
        idx = int(image_index)
    except Exception:
        return None
    if idx < 0:
        return None
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT image_data, mime_type
                FROM figma_inspection_thumbnails
                WHERE figma_inspection_id = %s AND image_index = %s
                """,
                (fid, idx),
            )
            row = cur.fetchone()
            if not row:
                return None
            raw = row.get("image_data")
            if isinstance(raw, memoryview):
                blob = raw.tobytes()
            elif isinstance(raw, bytes):
                blob = raw
            else:
                blob = bytes(raw) if raw is not None else b""
            mt = (row.get("mime_type") or "image/jpeg").strip() or "image/jpeg"
            return (blob, mt)


def update_figma_inspection_notified(id: int, notified_teams: bool) -> bool:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE figma_inspections SET notified_teams = %s WHERE id = %s",
                (bool(notified_teams), int(id)),
            )
            ok = cur.rowcount > 0
        conn.commit()
        return ok
