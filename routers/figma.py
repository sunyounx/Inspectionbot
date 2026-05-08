from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from google.genai import types
from pydantic import BaseModel

from db.database import (
    get_active_history,
    get_figma_comment_image,
    get_figma_inspection_by_id,
    get_figma_inspection_thumbnail,
    get_guidelines,
    get_terms,
    insert_figma_inspection,
    insert_figma_inspection_thumbnail,
    list_figma_inspection_thumbnails_meta,
    update_figma_inspection_notified,
)
from prompts.inspect import build_system_prompt as build_inspect_prompt
from services.figma_service import (
    FigmaRateLimitError,
    download_figma_image,
    export_nodes_as_pngs,
    get_file_info,
    get_image_children,
    normalize_figma_node_id,
)
from services.gemini_service import GEMINI_SEMAPHORE, inspect_creative, inspect_creative_json
from services.image_utils import resize_thumbnail
from services.inspect_formatter import format_inspection_results
from services.teams_service import send_inspection_notification

router = APIRouter(prefix="/api", tags=["figma"], redirect_slashes=True)

_MAX_FIGMA_IMAGES = 10


class FigmaInspectBody(BaseModel):
    file_key: str
    node_id: str
    message: str | None = None
    figma_url: str | None = None


class FigmaNotifyBody(BaseModel):
    inspection_id: int


def _ensure_token() -> None:
    if not (os.getenv("FIGMA_TOKEN") or "").strip():
        raise HTTPException(
            status_code=503,
            detail="FIGMA_TOKEN이 설정되지 않았습니다. 서버 환경 변수를 확인하세요.",
        )


@router.post("/figma/inspect")
async def figma_inspect(body: FigmaInspectBody):
    _ensure_token()
    file_key = (body.file_key or "").strip()
    node_id = normalize_figma_node_id((body.node_id or "").strip())
    if not file_key or not node_id:
        raise HTTPException(status_code=400, detail="file_key and node_id are required")

    try:
        finfo = await asyncio.to_thread(get_file_info, file_key)
    except FigmaRateLimitError as e:
        raise HTTPException(status_code=429, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Figma 파일 조회 실패: {e}") from e

    file_name = (finfo.get("name") or file_key)[:500]

    try:
        image_children = await asyncio.to_thread(get_image_children, file_key, node_id)
    except FigmaRateLimitError as e:
        raise HTTPException(status_code=429, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Figma 노드 조회 실패: {e}") from e

    skipped_n = 0
    if image_children:
        if len(image_children) > _MAX_FIGMA_IMAGES:
            skipped_n = len(image_children) - _MAX_FIGMA_IMAGES
            image_children = image_children[:_MAX_FIGMA_IMAGES]
        export_ids = [normalize_figma_node_id(n["id"]) for n in image_children]
        display_names = [((n.get("name") or "").strip() or file_name)[:200] for n in image_children]
    else:
        export_ids = [node_id]
        display_names = [file_name[:200]]

    try:
        cdn_map = await asyncio.to_thread(export_nodes_as_pngs, file_key, export_ids, 2)
    except FigmaRateLimitError as e:
        raise HTTPException(status_code=429, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Figma 이미지 내보내기 실패: {e}") from e

    if not cdn_map or all(not v for v in cdn_map.values()):
        raise HTTPException(status_code=502, detail="Figma에서 이미지 URL을 받지 못했습니다. node-id·권한을 확인하세요.")

    raw_pngs: list[tuple[bytes, str] | None] = []
    for eid, dname in zip(export_ids, display_names):
        cdn_url = cdn_map.get(eid)
        if not cdn_url:
            raw_pngs.append(None)
            continue
        raw = await asyncio.to_thread(download_figma_image, cdn_url)
        if not raw:
            raw_pngs.append(None)
            continue
        raw_pngs.append((raw, dname))

    if not any(x is not None for x in raw_pngs):
        raise HTTPException(status_code=502, detail="Figma CDN에서 이미지를 다운로드하지 못했습니다.")

    image_payloads: list[tuple[bytes, str, str]] = []
    pending_thumbnails: list[dict[str, Any]] = []
    thumb_index = 0
    images_meta: list[dict[str, Any]] = []

    for pair in raw_pngs:
        if pair is None:
            continue
        raw_png, dname = pair
        try:
            img800, mt800 = await asyncio.to_thread(resize_thumbnail, raw_png, 800)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"이미지 처리 실패: {e}") from e
        image_payloads.append((img800, mt800, dname))
        images_meta.append({"id": file_key, "name": dname})

        try:
            thumb400, thumb_mt = await asyncio.to_thread(resize_thumbnail, raw_png, 400)
        except Exception:
            thumb400, thumb_mt = img800, mt800

        pending_thumbnails.append(
            {
                "image_index": thumb_index,
                "file_name": dname,
                "mime_type": thumb_mt,
                "image_data": thumb400,
            }
        )
        thumb_index += 1

    if not image_payloads:
        raise HTTPException(status_code=502, detail="유효한 이미지가 없습니다. node-id·권한을 확인하세요.")

    user_msg = (body.message or "").strip() or "이 Figma 프레임의 소재를 검수해주세요."
    if skipped_n:
        user_msg += f"\n\n(참고: 이미지 노드가 많아 최대 {len(image_payloads)}장만 검수했고, {skipped_n}개는 제외했습니다.)"

    history = get_active_history()
    guidelines = get_guidelines()
    terms = get_terms()
    system_prompt = build_inspect_prompt(history=history, guidelines=guidelines, terms=terms)
    rules_n = len(history)

    total_imgs = len(image_payloads)

    if total_imgs <= 1:
        parts: list[Any] = []
        for d, mt, _name in image_payloads:
            parts.append(types.Part.from_bytes(data=d, mime_type=mt))
        parts.append(f"광고주 요청: {user_msg}\n이 소재를 검수해주세요.")
        async with GEMINI_SEMAPHORE:
            feedback = await asyncio.to_thread(inspect_creative, system_prompt, parts)
    else:
        async def inspect_one(d: bytes, mt: str, name: str, index: int, total: int) -> dict[str, Any]:
            async with GEMINI_SEMAPHORE:
                parts_one: list[Any] = [
                    types.Part.from_bytes(data=d, mime_type=mt),
                    (
                        f"파일명: {name}. 총 {total}장 중 {index}번째.\n"
                        "JSON으로 검수 결과만 출력하세요. 반드시 JSON만 출력하세요."
                    ),
                ]
                return await asyncio.to_thread(inspect_creative_json, system_prompt, parts_one)

        tasks = [
            inspect_one(d, mt, name, i + 1, total_imgs)
            for i, (d, mt, name) in enumerate(image_payloads)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        feedback = format_inspection_results(results, total_imgs)

    figma_url = (body.figma_url or "").strip() or None
    new_id = insert_figma_inspection(
        {
            "file_key": file_key,
            "file_name": file_name,
            "node_id": node_id,
            "figma_url": figma_url,
            "feedback": feedback,
            "rules_checked": rules_n,
            "file_count": total_imgs,
            "notified_teams": False,
        }
    )

    for thumb in pending_thumbnails:
        try:
            insert_figma_inspection_thumbnail(
                new_id,
                thumb["image_index"],
                thumb["file_name"],
                thumb["mime_type"],
                thumb["image_data"],
            )
        except Exception as e:
            print(f"[figma_inspect] thumbnail save failed idx={thumb.get('image_index')}: {e}", flush=True)

    return {
        "ok": True,
        "id": new_id,
        "file_key": file_key,
        "file_name": file_name,
        "node_id": node_id,
        "file_count": total_imgs,
        "skipped": skipped_n,
        "feedback": feedback,
        "rules_checked": rules_n,
        "figma_url": figma_url,
        "notified_teams": False,
        "images": images_meta,
    }


@router.get("/figma/inspections/{id}")
def get_figma_inspection_public(id: int):
    row = get_figma_inspection_by_id(id)
    if not row:
        raise HTTPException(status_code=404, detail="figma inspection not found")
    fk = (row.get("file_key") or "").strip()
    meta = list_figma_inspection_thumbnails_meta(id)
    if meta:
        images = [{"id": fk or "figma", "name": (m.get("file_name") or "").strip()} for m in meta]
    else:
        images = [{"id": fk or "figma", "name": (row.get("file_name") or "")}]
    return {**row, "images": images}


@router.get("/figma/inspection-image/{figma_inspection_id}/{image_index}")
def figma_inspection_image_public(figma_inspection_id: int, image_index: int):
    row = get_figma_inspection_thumbnail(figma_inspection_id, image_index)
    if not row:
        raise HTTPException(status_code=404, detail="image not found")
    blob, mt = row
    return Response(
        content=blob,
        media_type=mt,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/figma/comment-image/{file_key}/{comment_id}")
def figma_comment_image(file_key: str, comment_id: str):
    """광고주 Figma 댓글이 붙은 노드 PNG 서빙. figma_comment_images 테이블에서 조회."""
    row = get_figma_comment_image(file_key, comment_id)
    if not row:
        raise HTTPException(status_code=404, detail="figma comment image not found")
    blob = row.get("image_data")
    if not blob:
        raise HTTPException(status_code=404, detail="figma comment image empty")
    mt = row.get("mime_type") or "image/png"
    return Response(
        content=bytes(blob),
        media_type=mt,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.post("/figma/notify")
async def figma_notify(body: FigmaNotifyBody):
    ins = get_figma_inspection_by_id(int(body.inspection_id))
    if not ins:
        raise HTTPException(status_code=404, detail="figma inspection not found")

    if bool(ins.get("notified_teams")):
        return {"ok": True, "already_sent": True}

    title = f"[Figma 검수] {(ins.get('file_name') or ins.get('file_key') or '').strip()}"
    feedback = (ins.get("feedback") or "").strip()
    issues_guess = feedback.count("❌") + feedback.count("⚠️")
    figma_url = (ins.get("figma_url") or "").strip() or None
    app_url = (os.getenv("APP_URL") or "").strip() or None
    iid = int(body.inspection_id)
    thumb_urls: list[str] = []
    if app_url:
        base = app_url.rstrip("/")
        n = int(ins.get("file_count") or 0)
        for idx in range(max(0, n)):
            thumb_urls.append(f"{base}/api/figma/inspection-image/{iid}/{idx}")

    teams_result = await send_inspection_notification(
        title=title,
        inspection_id=iid,
        feedback=feedback,
        file_count=int(ins.get("file_count") or 0),
        issues_count=issues_guess,
        drive_url=figma_url,
        app_url=app_url,
        image_urls=thumb_urls,
        result_url_query=f"figma_inspection_id={iid}",
    )
    ok = bool(teams_result.get("ok")) if not teams_result.get("skipped") else False
    try:
        update_figma_inspection_notified(iid, ok)
    except Exception:
        pass

    return {"ok": True, "teams": teams_result}
