from __future__ import annotations

import asyncio
import os
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import Response
from google.genai import types
from pydantic import BaseModel
from starlette.background import BackgroundTask
from starlette.responses import JSONResponse

from db.database import (
    get_active_history,
    get_files_by_message_ts,
    get_files_by_ts_list,
    get_guidelines,
    get_history_by_topic,
    get_pending_approval_by_id,
    count_pending_approvals_for_admin,
    get_pending_approvals_for_admin,
    delete_slack_inspection,
    get_slack_inspection_by_id,
    get_slack_inspection_id_by_pending,
    get_slack_inspection_thumbnail,
    get_terms,
    insert_history,
    insert_slack_inspection,
    insert_slack_inspection_thumbnail,
    update_history_status,
    update_pending_status,
    update_pending_teams_notified,
)
from prompts.inspect import build_system_prompt as build_inspect_prompt
from services.gdrive_auth import ensure_gdrive_access_token, get_gdrive_session_id
from services.gdrive_service import read_workspace_document
from services.gemini_service import (
    GEMINI_SEMAPHORE,
    inspect_creative,
    invalidate_system_cache,
    refine_with_document,
)
from services.image_utils import resize_thumbnail
from services.notion_service import read_notion_page
from services.slack_service import (
    download_slack_image,
    extract_document_links,
    extract_notion_links,
)
from services.teams_service import send_slack_feedback_notification


router = APIRouter(prefix="/api", tags=["approval"], redirect_slashes=True)

_MAX_SLACK_IMAGES = 3

_ALLOWED_CATEGORIES = frozenset({"크리에이티브", "프로모션", "CRM", "브랜딩", "퍼포먼스", "기타", "미분류"})


async def _ensure_token_for_docs(
    pending: dict[str, Any], request: Request
) -> str | None:
    """pending의 full_text에 Google 문서 링크가 있으면 OAuth 토큰을 확인."""
    full_raw = (pending.get("full_text") or "").strip()
    doc_links = extract_document_links(full_raw)
    sid = get_gdrive_session_id(request)
    access_token: str | None = None
    if sid:
        try:
            access_token, _ = await ensure_gdrive_access_token(sid)
        except HTTPException:
            access_token = None
        except Exception:
            access_token = None
    if doc_links and not access_token:
        raise HTTPException(
            status_code=412,
            detail={
                "code": "gdrive_auth_required",
                "message": "Google Drive 로그인이 필요합니다. 로그인 후 다시 승인을 눌러주세요.",
                "link_count": len(doc_links),
            },
        )
    return access_token


def _dedupe_files_by_url(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in rows:
        u = (r.get("url") or "").strip()
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(r)
    return out


def _is_slack_image_file(f: dict[str, Any]) -> bool:
    mm = (f.get("mimetype") or "").lower()
    if mm.startswith("image/"):
        return True
    ft = (f.get("filetype") or "").lower()
    if ft in ("png", "jpg", "jpeg", "gif", "webp", "heic", "heif"):
        return True
    et = (f.get("external_type") or "").lower()
    return et == "slack_upload" and bool(ft)


class ApprovalCategoryBody(BaseModel):
    category: str | None = None


class ConflictResolveBody(BaseModel):
    action: Literal["use_new", "keep_old", "keep_both"]
    category: str | None = None


def _normalize_category(value: str | None) -> str | None:
    if not value or not isinstance(value, str):
        return None
    s = value.strip()
    return s if s in _ALLOWED_CATEGORIES else None


def _history_category(pending: dict[str, Any], refined_category: str) -> str:
    pc = _normalize_category(pending.get("category") if isinstance(pending.get("category"), str) else None)
    rc = _normalize_category(refined_category)
    return pc or rc or "크리에이티브"


def _history_category_with_override(
    pending: dict[str, Any],
    refined_category: str,
    override: str | None,
) -> str:
    oc = _normalize_category(override)
    if oc:
        return oc
    return _history_category(pending, refined_category)


async def _insert_refined_history_with_token(
    pending: dict[str, Any],
    access_token: str | None,
    *,
    category_override: str | None = None,
) -> int:
    full_raw = pending.get("full_text") or ""
    if isinstance(full_raw, str):
        full_raw = full_raw.strip()
    else:
        full_raw = str(full_raw or "")

    doc_links = extract_document_links(full_raw)
    notion_links = extract_notion_links(full_raw)
    parts_doc: list[str] = []

    if doc_links:
        if not access_token:
            raise RuntimeError(
                "Google Drive 로그인이 필요합니다. 로그인 후 다시 승인을 눌러주세요."
            )
        print(f"[approve] reading {len(doc_links)} doc links (using {min(len(doc_links), 5)})", flush=True)
        for link in doc_links[:5]:
            try:
                blob = await asyncio.to_thread(
                    read_workspace_document,
                    link["file_id"],
                    link["type"],
                    access_token,
                )
            except Exception as e:
                print(f"[approve] doc read failed {link['type']} {link['file_id']}: {e}", flush=True)
                raise RuntimeError(
                    f"Google 문서 읽기 실패 ({link['type']} {link['file_id']}): {e}"
                ) from e
            if blob:
                parts_doc.append(f"[{link['type']} {link['file_id']}]\n{blob}")
                print(f"[approve] doc ok {link['type']} {link['file_id']} ({len(blob)} chars)", flush=True)
            else:
                print(f"[approve] doc read failed {link['type']} {link['file_id']}: empty/unsupported", flush=True)
                raise RuntimeError(
                    f"Google 문서를 읽을 수 없습니다 ({link['type']} {link['file_id']}). "
                    "지원하지 않는 파일이거나 접근 권한이 없습니다."
                )

    if notion_links:
        print(f"[approve] reading {len(notion_links)} notion links (using {min(len(notion_links), 5)})", flush=True)
        for link in notion_links[:5]:
            url = link["url"]
            try:
                blob = await asyncio.to_thread(read_notion_page, url)
            except Exception as e:
                print(f"[approve] notion read failed {url}: {e}", flush=True)
                raise RuntimeError(f"Notion 페이지 읽기 실패 ({url}): {e}") from e
            if blob:
                parts_doc.append(f"[notion {url}]\n{blob}")
                print(f"[approve] notion ok {url} ({len(blob)} chars)", flush=True)
            else:
                # Notion 빈 페이지: integration 접근은 됐으나 본문 없음 → soft-fail(적재 계속).
                # Google은 None이 권한/미지원/읽기 실패이므로 hard-fail.
                print(f"[approve] notion empty page {url}", flush=True)

    doc_content = "\n\n---\n\n".join(parts_doc) if parts_doc else None

    refined = await asyncio.to_thread(refine_with_document, full_raw, doc_content)

    cat = _history_category_with_override(pending, refined.category, category_override)

    new_id = insert_history(
        {
            "date": refined.date,
            "topic": refined.topic,
            "summary": refined.summary,
            "scope": refined.scope,
            "type": refined.type,
            "category": cat,
            "full_text": full_raw or None,
            "original_quote": refined.original_quote,
            "slack_link": pending.get("slack_link"),
            "source_ts": pending.get("source_ts"),
            "author_user_id": pending.get("author_user_id"),
            "author_name": pending.get("author_name"),
            "message_time": pending.get("message_time"),
            "status": "활성",
        }
    )
    invalidate_system_cache()
    return int(new_id)


@router.get("/approvals")
def list_approvals(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: str | None = None,
    q: str | None = None,
    author: str | None = None,
    order: str = "desc",
):
    ord_ = order if order in ("asc", "desc") else "desc"
    items = get_pending_approvals_for_admin(
        limit=limit,
        offset=offset,
        status=status,
        q=q,
        author=author,
        order=ord_,
    )
    total = count_pending_approvals_for_admin(status=status, q=q, author=author)
    ts_list: list[str] = []
    for x in items:
        for key in ("parent_ts", "source_ts"):
            t = (x.get(key) or "").strip()
            if t:
                ts_list.append(t)
    uniq_ts = list(dict.fromkeys(ts_list))
    files_map = get_files_by_ts_list([str(t) for t in uniq_ts if t])
    for x in items:
        pts = (x.get("parent_ts") or "").strip()
        sts = (x.get("source_ts") or "").strip()
        merged: list[dict[str, Any]] = []
        if pts:
            merged.extend(files_map.get(pts, []))
        if sts:
            merged.extend(files_map.get(sts, []))
        x["files"] = _dedupe_files_by_url(merged)
    return {
        "items": items,
        "total": total,
        "has_more": offset + len(items) < total,
    }


@router.post("/approvals/{id}/approve")
async def approve(
    id: int,
    request: Request,
    body: ApprovalCategoryBody = Body(default=ApprovalCategoryBody()),
):
    pending = get_pending_approval_by_id(id)
    if not pending:
        raise HTTPException(status_code=404, detail="pending approval not found")
    if pending.get("status") != "대기중":
        raise HTTPException(status_code=400, detail="pending approval is not pending")

    access_token = await _ensure_token_for_docs(pending, request)

    update_pending_status(id, "처리중")

    async def bg_refine() -> None:
        async with GEMINI_SEMAPHORE:
            try:
                row = get_pending_approval_by_id(id)
                if not row or row.get("status") != "처리중":
                    return
                await _insert_refined_history_with_token(
                    row,
                    access_token,
                    category_override=body.category,
                )
                update_pending_status(id, "승인됨")
            except Exception as e:
                print(f"[bg_refine] 실패: {e}", flush=True)
                update_pending_status(id, "대기중")

    return JSONResponse(
        {"ok": True, "status": "processing"},
        background=BackgroundTask(bg_refine),
    )


@router.post("/approvals/{id}/reject")
def reject(id: int):
    pending = get_pending_approval_by_id(id)
    if not pending:
        raise HTTPException(status_code=404, detail="pending approval not found")
    if pending.get("status") != "대기중":
        raise HTTPException(status_code=400, detail="pending approval is not pending")

    update_pending_status(id, "폐기됨")
    return {"ok": True}


@router.post("/approvals/{id}/conflict")
async def resolve_conflict(id: int, body: ConflictResolveBody, request: Request):
    pending = get_pending_approval_by_id(id)
    if not pending:
        raise HTTPException(status_code=404, detail="pending approval not found")
    if pending.get("status") != "대기중":
        raise HTTPException(status_code=400, detail="pending approval is not pending")

    if int(pending.get("has_conflict") or 0) != 1:
        raise HTTPException(status_code=400, detail="pending approval has no conflict")

    action = body.action
    today = date.today().isoformat()

    if action == "use_new":
        access_token = await _ensure_token_for_docs(pending, request)
        old_id = pending.get("conflict_old_history_id")

        update_pending_status(id, "처리중")

        async def bg_use_new() -> None:
            async with GEMINI_SEMAPHORE:
                try:
                    row = get_pending_approval_by_id(id)
                    if not row or row.get("status") != "처리중":
                        return
                    await _insert_refined_history_with_token(
                        row,
                        access_token,
                        category_override=body.category,
                    )
                    if old_id:
                        update_history_status(int(old_id), "변경됨", today)
                        invalidate_system_cache()
                    update_pending_status(id, "승인됨")
                except Exception as e:
                    print(f"[bg_use_new] 실패: {e}", flush=True)
                    update_pending_status(id, "대기중")

        return JSONResponse(
            {"ok": True, "action": "use_new", "status": "processing"},
            background=BackgroundTask(bg_use_new),
        )

    if action == "keep_old":
        update_pending_status(id, "폐기됨")
        return {"ok": True, "action": "keep_old"}

    if action == "keep_both":
        access_token = await _ensure_token_for_docs(pending, request)
        update_pending_status(id, "처리중")

        async def bg_keep_both() -> None:
            async with GEMINI_SEMAPHORE:
                try:
                    row = get_pending_approval_by_id(id)
                    if not row or row.get("status") != "처리중":
                        return
                    await _insert_refined_history_with_token(
                        row,
                        access_token,
                        category_override=body.category,
                    )
                    update_pending_status(id, "승인됨")
                except Exception as e:
                    print(f"[bg_keep_both] 실패: {e}", flush=True)
                    update_pending_status(id, "대기중")

        return JSONResponse(
            {"ok": True, "action": "keep_both", "status": "processing"},
            background=BackgroundTask(bg_keep_both),
        )

    raise HTTPException(status_code=400, detail="invalid action")


@router.post("/approvals/{id}/inspect-and-notify")
async def inspect_and_notify(id: int):
    """
    슬랙 첨부 이미지로 Gemini 검수 후 Teams 전송. pending 상태는 유지(적재와 독립).
    """
    pending = get_pending_approval_by_id(id)
    if not pending:
        raise HTTPException(status_code=404, detail="pending approval not found")
    if pending.get("status") != "대기중":
        raise HTTPException(status_code=400, detail="pending approval is not pending")
    if int(pending.get("teams_notified") or 0) == 1:
        return {"ok": False, "already_sent": True, "detail": "이미 Teams로 전송되었습니다."}

    old_sid = get_slack_inspection_id_by_pending(id)
    if old_sid:
        delete_slack_inspection(old_sid)

    source_ts = (pending.get("source_ts") or "").strip()
    parent_ts = (pending.get("parent_ts") or "").strip()
    parent_files = get_files_by_message_ts(parent_ts) if parent_ts else []
    self_files = get_files_by_message_ts(source_ts) if source_ts else []
    files = _dedupe_files_by_url(parent_files + self_files)
    img_files = [f for f in files if _is_slack_image_file(f)][: _MAX_SLACK_IMAGES]
    raw_text = (pending.get("full_text") or "").strip() or ""

    app_url = (os.getenv("APP_URL") or "").strip() or None
    slack_link = (pending.get("slack_link") or "").strip() or None
    title = f"[소재 피드백] {(pending.get('topic') or '').strip() or '피드백'}"

    downloaded: list[tuple[dict[str, Any], bytes]] = []
    for f in img_files:
        url = (f.get("url") or "").strip()
        if not url:
            continue
        data = await asyncio.to_thread(download_slack_image, url)
        if data:
            downloaded.append((f, data))

    if not downloaded:
        feed = (
            "이미지가 첨부되지 않아 AI 검수를 생략했습니다.\n\n"
            + (f"광고주 원문:\n{raw_text}" if raw_text else "")
        )
        sid = insert_slack_inspection(
            {
                "pending_approval_id": int(id),
                "original_text": raw_text,
                "feedback": feed,
                "rules_checked": 0,
                "file_count": 0,
            }
        )
        teams_result = await send_slack_feedback_notification(
            title=title,
            slack_inspection_id=sid,
            original_text=raw_text,
            feedback=None,
            file_count=0,
            slack_permalink=slack_link,
            app_url=app_url,
            image_urls=None,
            text_only=True,
        )
        ok = bool(teams_result.get("ok")) and not teams_result.get("skipped")
        if ok:
            update_pending_teams_notified(id, True)
        return {
            "ok": True,
            "slack_inspection_id": sid,
            "teams": teams_result,
            "images_used": 0,
            "gemini_skipped": True,
        }

    parts: list[Any] = []
    for _f, raw_bytes in downloaded:
        rb, mt = await asyncio.to_thread(resize_thumbnail, raw_bytes, 800)
        parts.append(types.Part.from_bytes(data=rb, mime_type=mt))
    user_msg = f"광고주 피드백: {raw_text}\n이 소재를 검수해주세요."
    parts.append(user_msg)

    history = get_active_history()
    guidelines = get_guidelines()
    terms = get_terms()
    system_prompt = build_inspect_prompt(history=history, guidelines=guidelines, terms=terms)
    async with GEMINI_SEMAPHORE:
        feedback = await asyncio.to_thread(inspect_creative, system_prompt, parts)
    rules_n = len(history)

    sid = insert_slack_inspection(
        {
            "pending_approval_id": int(id),
            "original_text": raw_text,
            "feedback": feedback,
            "rules_checked": rules_n,
            "file_count": len(downloaded),
        }
    )

    for idx, (f, raw_bytes) in enumerate(downloaded):
        try:
            thumb_data, thumb_mt = await asyncio.to_thread(resize_thumbnail, raw_bytes, 400)
        except Exception:
            thumb_data = raw_bytes
            thumb_mt = (f.get("mimetype") or "image/jpeg").strip() or "image/jpeg"
        fid = f.get("file_id")
        insert_slack_inspection_thumbnail(
            sid,
            idx,
            str(fid) if fid is not None else None,
            (f.get("name") or None) if isinstance(f.get("name"), str) else None,
            thumb_mt,
            thumb_data,
        )

    base = (app_url or "").rstrip("/")
    image_urls: list[str] = []
    if base:
        image_urls = [f"{base}/api/slack-inspection-image/{sid}/{i}" for i in range(len(downloaded))]

    teams_result = await send_slack_feedback_notification(
        title=title,
        slack_inspection_id=sid,
        original_text=raw_text,
        feedback=feedback,
        file_count=len(downloaded),
        slack_permalink=slack_link,
        app_url=app_url,
        image_urls=image_urls,
        text_only=False,
    )
    ok = bool(teams_result.get("ok")) and not teams_result.get("skipped")
    if ok:
        update_pending_teams_notified(id, True)
    return {
        "ok": True,
        "slack_inspection_id": sid,
        "teams": teams_result,
        "images_used": len(downloaded),
        "gemini_skipped": False,
    }


@router.get("/slack-inspections/{slack_id}")
def get_slack_inspection_public(slack_id: int):
    row = get_slack_inspection_by_id(slack_id)
    if not row:
        raise HTTPException(status_code=404, detail="slack inspection not found")
    return row


@router.get("/slack-inspection-image/{slack_inspection_id}/{image_index}")
def slack_inspection_image_public(slack_inspection_id: int, image_index: int):
    row = get_slack_inspection_thumbnail(slack_inspection_id, image_index)
    if not row:
        raise HTTPException(status_code=404, detail="image not found")
    blob, mt = row
    return Response(
        content=blob,
        media_type=mt,
        headers={"Cache-Control": "public, max-age=86400"},
    )
