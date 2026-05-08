from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from models.schemas import FEEDBACK_CATEGORY

from db.database import (
    delete_history,
    get_files_by_ts_list,
    get_history,
    get_raw_messages,
    get_raw_thread_replies,
    insert_history,
    update_history,
    update_history_status,
)
from services.gemini_service import invalidate_system_cache


router = APIRouter(prefix="/api", tags=["history"], redirect_slashes=True)


class HistoryCreateBody(BaseModel):
    date: str
    topic: str
    summary: str
    scope: str
    type: str
    full_text: Optional[str] = None
    original_quote: Optional[str] = None
    slack_link: Optional[str] = None
    category: FEEDBACK_CATEGORY | None = None


class HistoryStatusPatchBody(BaseModel):
    status: str


class HistoryPutBody(BaseModel):
    topic: str
    summary: str
    scope: Literal["영상", "이미지DA", "카피", "전체"]
    type: Literal["방향성", "규칙"]
    full_text: Optional[str] = None
    original_quote: Optional[str] = None
    category: FEEDBACK_CATEGORY | None = None


@router.get("/history")
def list_history(status: str | None = None, category: str | None = None):
    items = get_history(status=status, category=category)
    ts_list = [x.get("source_ts") for x in items if x.get("source_ts")]
    files_map = get_files_by_ts_list([str(t) for t in ts_list if t])
    for x in items:
        ts = (x.get("source_ts") or "").strip()
        x["files"] = files_map.get(ts, []) if ts else []
    return items


@router.get("/raw-messages")
def list_raw_messages(
    limit: int = 100,
    offset: int = 0,
    kind: str | None = None,
    q: str | None = None,
    author: str | None = None,
    has_files: bool | None = Query(None),
    order: str = "desc",
):
    """kind: 생략=전체, feedback | not_feedback | bot — 최상위 메시지만(parent_ts NULL)."""
    fk = kind if kind in ("feedback", "not_feedback", "bot") else None
    ord_ = order if order in ("asc", "desc") else "desc"
    items = get_raw_messages(
        limit=min(max(limit, 1), 500),
        offset=max(offset, 0),
        filter_kind=fk,
        q=q,
        author=author,
        has_files=has_files,
        order=ord_,
    )
    ts_list = [x.get("ts") for x in items if x.get("ts")]
    files_map = get_files_by_ts_list([str(t) for t in ts_list if t])
    for x in items:
        ts = (x.get("ts") or "").strip()
        x["files"] = files_map.get(ts, []) if ts else []
    return items


@router.get("/raw-messages/thread")
def list_raw_thread_messages(parent_ts: str):
    """특정 부모 ts의 스레드 댓글만(시간순)."""
    items = get_raw_thread_replies(parent_ts)
    ts_list = [x.get("ts") for x in items if x.get("ts")]
    files_map = get_files_by_ts_list([str(t) for t in ts_list if t])
    for x in items:
        ts = (x.get("ts") or "").strip()
        x["files"] = files_map.get(ts, []) if ts else []
    return items


@router.post("/history")
def create_history(body: HistoryCreateBody):
    row = {
        "date": body.date,
        "topic": body.topic,
        "summary": body.summary,
        "scope": body.scope,
        "type": body.type,
        "full_text": body.full_text,
        "original_quote": body.original_quote,
        "slack_link": body.slack_link,
        "status": "활성",
    }
    if body.category is not None:
        row["category"] = body.category
    new_id = insert_history(row)
    invalidate_system_cache()
    return {"id": new_id}


@router.patch("/history/{id}")
def patch_history_status(id: int, body: HistoryStatusPatchBody):
    update_history_status(id=id, status=body.status, changed_date=date.today().isoformat())
    invalidate_system_cache()
    return {"ok": True}


@router.put("/history/{id}")
def put_history(id: int, body: HistoryPutBody):
    fields = {
        "topic": body.topic,
        "summary": body.summary,
        "scope": body.scope,
        "type": body.type,
        "full_text": body.full_text,
        "original_quote": body.original_quote,
    }
    if body.category is not None:
        fields["category"] = body.category
    ok = update_history(id, fields)
    if not ok:
        raise HTTPException(status_code=404, detail="history not found")
    invalidate_system_cache()
    return {"ok": True}


@router.delete("/history/{id}")
def remove_history(id: int):
    if not delete_history(id):
        raise HTTPException(status_code=404, detail="history not found")
    invalidate_system_cache()
    return {"ok": True}

