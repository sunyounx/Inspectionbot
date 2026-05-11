from __future__ import annotations
import asyncio
from db.database import _connect
from services.polling import _process_potential_feedback

CUTOFF_TS = 1774969200.0  # 2026-04-01 00:00:00 KST

def _mark_notified(source_ts: str) -> None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE pending_approvals SET teams_notified = 1 "
            "WHERE source_ts = %s AND teams_notified = 0",
            (source_ts,),
        )
        conn.commit()

async def main() -> None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE pending_approvals SET status = '폐기됨' "
            "WHERE status = '대기중' "
            "AND CAST(source_ts AS DOUBLE PRECISION) >= %s",
            (CUTOFF_TS,),
        )
        discarded = cur.rowcount
        conn.commit()
    print(f"[rebuild] discarded {discarded} pending rows")

    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT ts, channel, user_id, text FROM slack_raw_messages "
            "WHERE parent_ts IS NULL AND is_bot = 0 "
            "AND channel NOT LIKE 'figma:%%' "
            "AND CAST(ts AS DOUBLE PRECISION) >= %s "
            "ORDER BY CAST(ts AS DOUBLE PRECISION) ASC",
            (CUTOFF_TS,),
        )
        tops = cur.fetchall()
    print(f"[rebuild] top-level msgs: {len(tops)}")

    for idx, m in enumerate(tops, 1):
        ts = (m.get("ts") or "").strip()
        text = (m.get("text") or "").strip()
        if not ts or not text:
            continue

        await _process_potential_feedback(
            channel=m["channel"], text=text,
            message_ts=ts, user_id=m.get("user_id"), parent_ts=None,
        )
        _mark_notified(ts)

        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT ts, channel, user_id, text FROM slack_raw_messages "
                "WHERE parent_ts = %s AND is_bot = 0 "
                "AND channel NOT LIKE 'figma:%%' "
                "ORDER BY CAST(ts AS DOUBLE PRECISION) ASC",
                (ts,),
            )
            replies = cur.fetchall()

        for r in replies:
            rts = (r.get("ts") or "").strip()
            rtext = (r.get("text") or "").strip()
            if not rts or not rtext:
                continue
            await _process_potential_feedback(
                channel=r["channel"], text=rtext,
                message_ts=rts, user_id=r.get("user_id"), parent_ts=ts,
            )
            _mark_notified(rts)

        if idx % 20 == 0:
            print(f"[rebuild] processed {idx}/{len(tops)}")

    print("[rebuild] done")

if __name__ == "__main__":
    asyncio.run(main())
