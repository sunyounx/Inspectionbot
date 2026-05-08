from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException, Request
from google.genai import types
from pydantic import BaseModel
from starlette.responses import JSONResponse, RedirectResponse
from starlette.background import BackgroundTask
from fastapi.responses import Response, StreamingResponse

from db.database import (
    add_saved_folder,
    clear_gdrive_oauth_token,
    get_active_history,
    get_gdrive_inspection_by_id,
    get_gdrive_oauth_token,
    get_guidelines,
    get_inspection_thumbnail,
    get_inspection_thumbnails,
    get_saved_folders,
    get_terms,
    insert_gdrive_inspection,
    insert_inspection_thumbnail,
    remove_saved_folder,
    upsert_gdrive_oauth_token,
    update_gdrive_inspection_notified,
)
from prompts.inspect import build_system_prompt as build_inspect_prompt
from services.gdrive_auth import ensure_gdrive_access_token, get_gdrive_session_id
from services.image_utils import resize_thumbnail
from services.video_utils import extract_frames_and_audio
from services.gdrive_service import (
    download_image,
    get_file_thumbnail_link,
    get_folder_name,
    get_parent_folder_id,
    list_images_in_folder,
    list_videos_in_folder,
)
from services.gemini_service import GEMINI_SEMAPHORE, inspect_creative, inspect_creative_json
from services.teams_service import send_inspection_notification
from services.inspect_formatter import format_inspection_results

router = APIRouter(prefix="/api", tags=["gdrive"], redirect_slashes=True)

_MAX_IMAGES = 10
_MAX_VIDEOS = 3
_OAUTH_SCOPE = "https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/userinfo.email"


def _drive_mtime_key(f: dict[str, Any]) -> str:
    return (f.get("modifiedTime") or f.get("createdTime") or "") or ""


def _ensure_session_cookie(resp: RedirectResponse, sid: str) -> None:
    secure = (os.getenv("COOKIE_SECURE") or "").strip().lower() in ("1", "true", "yes", "on")
    resp.set_cookie(
        "gdrive_session",
        sid,
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=60 * 60 * 24 * 30,
        path="/",
    )


def _oauth_env(name: str) -> str:
    v = (os.getenv(name) or "").strip()
    if not v:
        raise RuntimeError(f"Missing {name}")
    return v


def _redirect_uri() -> str:
    return _oauth_env("GOOGLE_REDIRECT_URI")


def _client_id() -> str:
    return _oauth_env("GOOGLE_CLIENT_ID")


def _client_secret() -> str:
    return _oauth_env("GOOGLE_CLIENT_SECRET")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _fetch_user_email(access_token: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if r.status_code >= 400:
                return None
            j = r.json()
            return (j.get("email") or "").strip() or None
    except Exception:
        return None


class GDriveInspectBody(BaseModel):
    folder_id: str
    file_ids: Optional[list[str]] = None
    message: Optional[str] = None


class GDriveNotifyBody(BaseModel):
    inspection_id: int
    recipient: Optional[str] = None


class GDriveSaveFolderBody(BaseModel):
    folder_id: str
    drive_url: Optional[str] = None


@router.get("/gdrive/files")
async def gdrive_files(request: Request, folder_id: str, limit: int = 50):
    sid = get_gdrive_session_id(request)
    if not sid:
        raise HTTPException(status_code=401, detail="Google Drive 로그인 필요")
    access_token, _ = await ensure_gdrive_access_token(sid)
    try:
        files = await asyncio.to_thread(list_images_in_folder, folder_id, access_token, limit)
    except Exception as e:
        msg = str(e)
        if "insufficientPermissions" in msg or "permission" in msg.lower():
            msg += " (해당 폴더가 로그인한 계정에 공유되어 있는지 확인하세요)"
        raise HTTPException(status_code=502, detail=f"Google Drive fetch failed: {msg}") from e
    return {"folder_id": folder_id, "files": files}


@router.get("/gdrive/parent-folder")
async def gdrive_parent_folder(request: Request, file_id: str):
    """Picker에서 선택한 파일의 직계 부모 폴더 id (검수 API folder_id 결정용)."""
    sid = get_gdrive_session_id(request)
    if not sid:
        raise HTTPException(status_code=401, detail="Google Drive 로그인 필요")
    fid = (file_id or "").strip()
    if not fid:
        raise HTTPException(status_code=400, detail="file_id is required")
    access_token, _ = await ensure_gdrive_access_token(sid)
    try:
        parent = await asyncio.to_thread(get_parent_folder_id, fid, access_token)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Google Drive metadata failed: {e}") from e
    if not parent:
        raise HTTPException(status_code=404, detail="parent folder not found")
    return {"folder_id": parent}


@router.get("/gdrive/oauth/token")
async def gdrive_oauth_token(request: Request):
    """Google Picker용 access_token (내부 도구·HTTPS 가정)."""
    sid = get_gdrive_session_id(request)
    if not sid:
        raise HTTPException(status_code=401, detail="Google Drive 로그인 필요")
    access_token, _ = await ensure_gdrive_access_token(sid)
    picker_key = (os.getenv("GOOGLE_PICKER_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip() or None
    root_folder_id = (os.getenv("GDRIVE_ROOT_FOLDER_ID") or "").strip() or None
    return {
        "access_token": access_token,
        "picker_api_key": picker_key,
        "root_folder_id": root_folder_id,
    }


@router.get("/gdrive/saved-folders")
def list_saved_folders(limit: int = 50):
    return get_saved_folders(limit=limit)


@router.post("/gdrive/saved-folders")
async def save_folder(body: GDriveSaveFolderBody, request: Request):
    folder_id = (body.folder_id or "").strip()
    if not folder_id:
        raise HTTPException(status_code=400, detail="folder_id is required")
    sid = get_gdrive_session_id(request)
    if not sid:
        raise HTTPException(status_code=401, detail="Google Drive 로그인 필요")
    access_token, _ = await ensure_gdrive_access_token(sid)
    try:
        folder_name = await asyncio.to_thread(get_folder_name, folder_id, access_token)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Google Drive fetch failed: {e} (해당 폴더가 로그인한 계정에 공유되어 있는지 확인하세요)",
        ) from e

    drive_url = (body.drive_url or "").strip() or f"https://drive.google.com/drive/folders/{folder_id}"
    try:
        new_id = add_saved_folder({"folder_id": folder_id, "folder_name": folder_name, "drive_url": drive_url})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save folder: {e}") from e
    return {"ok": True, "id": new_id, "folder_id": folder_id, "folder_name": folder_name, "drive_url": drive_url}


@router.delete("/gdrive/saved-folders/{id}")
def delete_saved_folder(id: int):
    if not remove_saved_folder(id):
        raise HTTPException(status_code=404, detail="saved folder not found")
    return {"ok": True}


@router.post("/gdrive/inspect")
async def gdrive_inspect(body: GDriveInspectBody, request: Request):
    folder_id = (body.folder_id or "").strip()
    if not folder_id:
        raise HTTPException(status_code=400, detail="folder_id is required")

    sid = get_gdrive_session_id(request)
    if not sid:
        raise HTTPException(status_code=401, detail="Google Drive 로그인 필요")

    access_token, tok = await ensure_gdrive_access_token(sid)
    try:
        folder_name = await asyncio.to_thread(get_folder_name, folder_id, access_token)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Google Drive fetch failed: {e} (해당 폴더가 로그인한 계정에 공유되어 있는지 확인하세요)",
        ) from e

    try:
        img_list = await asyncio.to_thread(list_images_in_folder, folder_id, access_token, 50)
        vid_list = await asyncio.to_thread(list_videos_in_folder, folder_id, access_token, 50)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Google Drive fetch failed: {e}") from e

    candidates = sorted(img_list + vid_list, key=_drive_mtime_key, reverse=True)

    if not candidates:
        raise HTTPException(status_code=404, detail="No image or video files found in the folder")

    if body.file_ids:
        chosen = [f for f in candidates if f.get("id") in set(body.file_ids)]
    else:
        chosen = candidates

    if not chosen:
        raise HTTPException(status_code=404, detail="No matching files found")

    images = [f for f in chosen if (f.get("mimeType") or "").startswith("image/")]
    videos = [f for f in chosen if (f.get("mimeType") or "").startswith("video/")]

    selected_images = images[:_MAX_IMAGES]
    selected_videos = videos[:_MAX_VIDEOS]
    skipped_n = max(0, len(images) - len(selected_images)) + max(0, len(videos) - len(selected_videos))

    print(
        f"[gdrive_inspect] folder_id={folder_id} img_candidates={len(images)} vid_candidates={len(videos)} "
        f"selected_img={len(selected_images)} selected_vid={len(selected_videos)} skipped={skipped_n}",
        flush=True,
    )

    if not selected_images and not selected_videos:
        raise HTTPException(status_code=404, detail="No image or video files to inspect")

    history = get_active_history()
    guidelines = get_guidelines()
    terms = get_terms()
    system_prompt = build_inspect_prompt(history=history, guidelines=guidelines, terms=terms)

    user_msg = (body.message or "").strip() or "이 폴더의 이미지·영상 소재를 검수해주세요."
    if skipped_n:
        user_msg += (
            f"\n\n(참고: 파일이 많아 이미지는 최대 {len(selected_images)}장, "
            f"영상은 최대 {len(selected_videos)}개만 검수했고, 나머지 {skipped_n}개는 제외했습니다.)"
        )

    feedback_blocks: list[str] = []
    file_names: list[str] = []
    images_meta: list[dict[str, Any]] = []
    pending_thumbnails: list[dict[str, Any]] = []
    thumb_index = 0

    image_payloads: list[tuple[bytes, str, str]] = []
    for f in selected_images:
        fid = (f.get("id") or "").strip()
        if not fid:
            continue
        try:
            data, mt = await asyncio.to_thread(download_image, fid, access_token)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Google Drive download failed: {e}") from e
        name = (f.get("name") or fid)[:200]
        file_names.append(name)
        images_meta.append({"id": fid, "name": name, "kind": "image"})
        # Gemini 입력은 800px 리사이즈본으로 통일 (토큰/속도 최적화)
        try:
            resized, resized_mt = await asyncio.to_thread(resize_thumbnail, data, 800)
            image_payloads.append((resized, resized_mt, name))
        except Exception:
            image_payloads.append((data, mt, name))

        try:
            thumb_data, thumb_mt = await asyncio.to_thread(resize_thumbnail, data)
        except Exception:
            thumb_data, thumb_mt = data, mt
        pending_thumbnails.append(
            {
                "image_index": thumb_index,
                "file_id": fid,
                "file_name": name,
                "mime_type": thumb_mt,
                "image_data": thumb_data,
            }
        )
        thumb_index += 1

    inspect_parts: list[Any] = []

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

    if image_payloads:
        if len(image_payloads) <= 1:
            # 1장은 기존 자유 텍스트(단일 호출) 유지
            parts_one: list[Any] = []
            d, mt, _name = image_payloads[0]
            parts_one.append(types.Part.from_bytes(data=d, mime_type=mt))
            parts_one.append(user_msg)
            async with GEMINI_SEMAPHORE:
                one_feedback = await asyncio.to_thread(inspect_creative, system_prompt, parts_one)
            feedback_blocks.append(one_feedback)
        else:
            tasks = [
                inspect_one(d, mt, name, i + 1, len(image_payloads))
                for i, (d, mt, name) in enumerate(image_payloads)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            feedback_blocks.append(format_inspection_results(results, len(image_payloads)))

    for vi, vf in enumerate(selected_videos):
        fid = (vf.get("id") or "").strip()
        if not fid:
            continue
        vname = (vf.get("name") or fid)[:200]
        file_names.append(vname)
        images_meta.append({"id": fid, "name": vname, "kind": "video"})
        try:
            vdata, vmt = await asyncio.to_thread(download_image, fid, access_token)
        except Exception as e:
            feedback_blocks.append(f"### 영상 {vi + 1}\n⚠️ 다운로드 실패: {e}")
            continue

        result = await asyncio.to_thread(extract_frames_and_audio, vdata)
        if not result["frames"] and not result["audio"]:
            feedback_blocks.append(f"### 영상 {vi + 1}\n⚠️ 프레임/오디오 추출 실패")
            continue

        for frame_data, frame_mt in result["frames"]:
            inspect_parts.append(types.Part.from_bytes(data=frame_data, mime_type=frame_mt))
        if result["audio"]:
            ad, amt = result["audio"]
            inspect_parts.append(types.Part.from_bytes(data=ad, mime_type=amt))
        audio_note = (
            "오디오(MP3)도 첨부되어 있습니다."
            if result["audio"]
            else "오디오는 없거나 추출되지 않았습니다."
        )
        inspect_parts.append(
            f"### 영상 {vi + 1} (파일명: {vname})\n"
            f"위 이미지들은 영상에서 시간 간격으로 샘플링한 프레임입니다. {audio_note} "
            "스크립트를 추출하고 소재를 검수해주세요."
        )

    if inspect_parts:
        inspect_parts.append(user_msg)
        async with GEMINI_SEMAPHORE:
            merged_feedback = await asyncio.to_thread(
                inspect_creative, system_prompt, inspect_parts
            )
        feedback_blocks.append(merged_feedback)

    feedback = "\n\n---\n\n".join(feedback_blocks)
    rules_checked = len(history)
    total_files = len(image_payloads) + len(selected_videos)

    drive_url = f"https://drive.google.com/drive/folders/{folder_id}"

    new_id = insert_gdrive_inspection(
        {
            "folder_id": folder_id,
            "folder_name": folder_name,
            "file_names": ", ".join(file_names),
            "image_ids": ",".join([m.get("id") or "" for m in images_meta]),
            "thumbnail_files": "",
            "file_count": total_files,
            "feedback": feedback,
            "rules_checked": rules_checked,
            "drive_url": drive_url,
            "notified_teams": False,
        }
    )

    for thumb in pending_thumbnails:
        try:
            insert_inspection_thumbnail(
                new_id,
                thumb["image_index"],
                thumb["file_id"],
                thumb["file_name"],
                thumb["mime_type"],
                thumb["image_data"],
            )
        except Exception as e:
            print(f"[gdrive_inspect] inspection_thumbnails save failed idx={thumb.get('image_index')}: {e}", flush=True)

    return {
        "ok": True,
        "id": new_id,
        "folder_id": folder_id,
        "folder_name": folder_name,
        "file_count": total_files,
        "image_count": len(image_payloads),
        "video_count": len(selected_videos),
        "total_in_folder": len(candidates),
        "skipped": skipped_n,
        "feedback": feedback,
        "rules_checked": rules_checked,
        "drive_url": drive_url,
        "notified_teams": False,
        "user_email": (tok.get("user_email") if isinstance(tok, dict) else None),
        "images": images_meta,
    }


@router.post("/gdrive/notify")
async def gdrive_notify(body: GDriveNotifyBody, request: Request):
    sid = get_gdrive_session_id(request)
    if not sid:
        raise HTTPException(status_code=401, detail="Google Drive 로그인 필요")
    # 세션이 살아있는지 확인(만료면 401)
    await ensure_gdrive_access_token(sid)

    ins = get_gdrive_inspection_by_id(int(body.inspection_id))
    if not ins:
        raise HTTPException(status_code=404, detail="inspection not found")

    # 이미 전송된 건은 재전송 금지(중복 클릭 방지)
    if bool(ins.get("notified_teams")):
        return {"ok": True, "already_sent": True}

    title = f"[Drive 검수] {(ins.get('folder_name') or ins.get('folder_id') or '').strip()}"
    feedback = (ins.get("feedback") or "").strip()
    issues_guess = feedback.count("❌") + feedback.count("⚠️")
    drive_url = (ins.get("drive_url") or "").strip() or None
    app_url = (os.getenv("APP_URL") or "").strip() or None
    thumb_urls: list[str] = []
    if app_url:
        base = app_url.rstrip("/")
        iid = int(body.inspection_id)
        try:
            thumb_rows = get_inspection_thumbnails(iid)
        except Exception:
            thumb_rows = []
        for row in thumb_rows:
            idx = int(row.get("image_index") or 0)
            thumb_urls.append(f"{base}/api/gdrive/inspection-image/{iid}/{idx}")

    teams_result = await send_inspection_notification(
        title=title,
        inspection_id=int(body.inspection_id),
        feedback=feedback,
        file_count=int(ins.get("file_count") or 0),
        issues_count=issues_guess,
        drive_url=drive_url,
        app_url=app_url,
        image_urls=thumb_urls,
    )
    ok = bool(teams_result.get("ok")) if not teams_result.get("skipped") else False
    try:
        update_gdrive_inspection_notified(int(body.inspection_id), ok)
    except Exception:
        pass

    return {"ok": True, "teams": teams_result}


@router.get("/gdrive/inspection-image/{inspection_id}/{image_index}")
def gdrive_inspection_image_public(inspection_id: int, image_index: int):
    """DB에 저장된 검수 썸네일 — 세션 불필요(공개 URL)."""
    row = get_inspection_thumbnail(inspection_id, image_index)
    if not row:
        raise HTTPException(status_code=404, detail="image not found")
    blob, mt = row
    return Response(
        content=blob,
        media_type=mt,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/gdrive/inspections/{id}")
async def get_gdrive_inspection(id: int, request: Request):
    sid = get_gdrive_session_id(request)
    if not sid:
        raise HTTPException(status_code=401, detail="Google Drive 로그인 필요")
    await ensure_gdrive_access_token(sid)
    ins = get_gdrive_inspection_by_id(int(id))
    if not ins:
        raise HTTPException(status_code=404, detail="inspection not found")
    image_ids_raw = (ins.get("image_ids") or "").strip()
    images = [{"id": fid.strip(), "name": ""} for fid in image_ids_raw.split(",") if fid.strip()]
    return {**ins, "images": images}


@router.get("/gdrive/thumbnail/{file_id}")
async def gdrive_thumbnail(file_id: str, request: Request):
    sid = get_gdrive_session_id(request)
    if not sid:
        raise HTTPException(status_code=401, detail="Google Drive 로그인 필요")
    access_token, _ = await ensure_gdrive_access_token(sid)

    fid = (file_id or "").strip()
    if not fid:
        raise HTTPException(status_code=400, detail="file_id is required")

    try:
        thumb_url = await asyncio.to_thread(get_file_thumbnail_link, fid, access_token)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Drive metadata failed: {e}") from e

    if thumb_url:
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                r = await client.get(
                    thumb_url,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            if r.status_code < 400:
                ct = r.headers.get("content-type") or "image/jpeg"
                return Response(content=r.content, media_type=ct)
        except Exception:
            pass

    # 썸네일 미생성/실패 시: 원본 스트리밍 (느릴 수 있음)
    client = httpx.AsyncClient(timeout=60.0)
    resp: httpx.Response | None = None
    try:
        url = f"https://www.googleapis.com/drive/v3/files/{fid}"
        params = {"alt": "media", "supportsAllDrives": "true"}
        req = client.build_request("GET", url, params=params, headers={"Authorization": f"Bearer {access_token}"})
        resp = await client.send(req, stream=True)
        if resp.status_code >= 400:
            body = await resp.aread()
            await resp.aclose()
            await client.aclose()
            raise HTTPException(status_code=502, detail=f"Drive media fetch failed: HTTP {resp.status_code} {body[:200].decode(errors='replace')}")

        ct = resp.headers.get("content-type") or "application/octet-stream"

        async def cleanup() -> None:
            await resp.aclose()
            await client.aclose()

        return StreamingResponse(resp.aiter_bytes(), media_type=ct, background=BackgroundTask(cleanup))
    except HTTPException:
        raise
    except Exception as e:
        if resp is not None:
            await resp.aclose()
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"Drive media fetch failed: {e}") from e


@router.get("/gdrive/oauth/login")
def oauth_login(request: Request):
    sid = get_gdrive_session_id(request) or str(uuid4())
    params = {
        "client_id": _client_id(),
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": _OAUTH_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    resp = RedirectResponse(url=url, status_code=302)
    _ensure_session_cookie(resp, sid)
    return resp


@router.get("/gdrive/oauth/callback")
async def oauth_callback(code: str, request: Request):
    code = (code or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="missing code")
    sid = get_gdrive_session_id(request) or str(uuid4())

    data = {
        "code": code,
        "client_id": _client_id(),
        "client_secret": _client_secret(),
        "redirect_uri": _redirect_uri(),
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post("https://oauth2.googleapis.com/token", data=data)
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"OAuth token exchange failed: {r.status_code} {r.text}")
    j = r.json()
    access_token = (j.get("access_token") or "").strip()
    refresh_token = (j.get("refresh_token") or "").strip() or None
    expires_in = j.get("expires_in")

    if not access_token:
        raise HTTPException(status_code=502, detail="OAuth token exchange failed: missing access_token")

    email = await _fetch_user_email(access_token)

    exp_at: datetime | None = None
    try:
        sec = int(expires_in or 0)
        exp_at = _utcnow() + timedelta(seconds=sec) if sec > 0 else None
    except Exception:
        exp_at = None

    upsert_gdrive_oauth_token(
        session_id=sid,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=exp_at,
        user_email=email,
    )
    resp = RedirectResponse(url="/static/index.html", status_code=302)
    _ensure_session_cookie(resp, sid)
    return resp


@router.get("/gdrive/oauth/status")
async def oauth_status(request: Request):
    sid = get_gdrive_session_id(request)
    if not sid:
        return {"logged_in": False}
    tok = get_gdrive_oauth_token(sid)
    if not tok:
        return {"logged_in": False}
    try:
        _, tok2 = await ensure_gdrive_access_token(sid)
        return {
            "logged_in": True,
            "user_email": tok2.get("user_email"),
            "has_refresh_token": bool(tok2.get("refresh_token")),
        }
    except HTTPException:
        return {"logged_in": False}


@router.delete("/gdrive/oauth/logout")
def oauth_logout(request: Request):
    sid = get_gdrive_session_id(request)
    if sid:
        clear_gdrive_oauth_token(sid)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("gdrive_session", path="/")
    return resp

