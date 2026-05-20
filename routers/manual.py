from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from db.database import get_gdrive_oauth_token
from models.schemas import FEEDBACK_CATEGORY
from routers.approval import _ensure_token_for_docs, _insert_refined_history_with_token
from services.gdrive_auth import get_gdrive_session_id
from services.gemini_service import GEMINI_SEMAPHORE
from services.slack_service import extract_document_links, extract_notion_links

KST = timezone(timedelta(hours=9))

router = APIRouter(prefix="/api", tags=["manual"], redirect_slashes=True)


class ManualIngestBody(BaseModel):
    text: str
    author_name: str | None = None
    category: FEEDBACK_CATEGORY | None = None


@router.post("/manual-ingest")
async def manual_ingest(body: ManualIngestBody, request: Request):
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    sid = get_gdrive_session_id(request)
    oauth_email: str | None = None
    oauth_name: str | None = None
    if sid:
        tok = get_gdrive_oauth_token(sid)
        if tok:
            oauth_email = (tok.get("user_email") or "").strip() or None
            if oauth_email:
                oauth_name = oauth_email.split("@", 1)[0]

    override = (body.author_name or "").strip()
    display_name = override or oauth_name or "수동 입력"
    display_name = f"[수동] {display_name}"

    now_kst = datetime.now(tz=KST)
    source_ts = f"{now_kst.timestamp():.3f}"
    message_time = now_kst.strftime("%Y-%m-%d %H:%M:%S")
    today_iso = date.today().isoformat()

    pending_dict = {
        "id": None,
        "date": today_iso,
        "full_text": text,
        "slack_link": None,
        "source_ts": source_ts,
        "author_user_id": oauth_email,
        "author_name": display_name,
        "message_time": message_time,
        "category": body.category or "미분류",
    }

    access_token = await _ensure_token_for_docs(pending_dict, request)
    doc_count = len(extract_document_links(text))
    notion_count = len(extract_notion_links(text))

    async with GEMINI_SEMAPHORE:
        try:
            history_id = await _insert_refined_history_with_token(
                pending_dict,
                access_token,
                category_override=body.category,
            )
        except Exception as e:
            print(f"[manual] refine/insert failed: {e}", flush=True)
            raise HTTPException(status_code=500, detail=f"refine 또는 적재 실패: {e}")

    return {
        "ok": True,
        "history_id": history_id,
        "doc_link_count": doc_count,
        "notion_link_count": notion_count,
    }
