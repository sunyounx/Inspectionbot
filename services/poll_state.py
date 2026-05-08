from __future__ import annotations

import time

from db.database import get_poll_state, set_poll_state

KEY = "last_poll_ts"


def load_last_poll_ts() -> str:
    """
    Slack conversations.history oldest 파라미터에 넣을 값(초 단위 float string).
    값이 없으면 최근 10분을 기본으로 합니다.
    """
    v = get_poll_state(KEY)
    if not v:
        return str(time.time() - 600)
    return str(v).strip() or str(time.time() - 600)


def save_last_poll_ts(ts: str) -> None:
    set_poll_state(KEY, str(ts))

