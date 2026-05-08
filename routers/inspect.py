from __future__ import annotations

import asyncio
import base64
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from google.genai import types

from db.database import (
    get_active_history,
    get_copybank,
    get_guidelines,
    get_raw_messages,
    get_raw_thread_replies_bulk,
    get_terms,
)
from models.schemas import InspectRequest, InspectResponse
from prompts.history_chat import build_system_prompt as build_history_prompt
from prompts.inspect import build_system_prompt as build_inspect_prompt
from prompts.raw_messages_chat import build_system_prompt as build_raw_messages_prompt
from prompts.create_copy import build_system_prompt as build_create_copy_prompt
from prompts.terms_chat import build_system_prompt as build_terms_prompt
from services.gemini_service import GEMINI_SEMAPHORE, inspect_creative
from services.image_utils import resize_thumbnail
from services.video_utils import extract_frames_and_audio


router = APIRouter(prefix="/api", tags=["inspect"], redirect_slashes=True)

_MAX_INSPECT_IMAGES = 8


def _normalize_image_pairs(req: InspectRequest) -> list[tuple[str, str]]:
    b = req.image_base64
    m = req.image_media_type
    if b is None and m is None:
        return []
    if b is None or m is None:
        raise HTTPException(
            status_code=400,
            detail="image_base64 and image_media_type must both be set or both omitted",
        )
    b_list: list[str] = [b] if isinstance(b, str) else list(b)
    m_list: list[str] = [m] if isinstance(m, str) else list(m)
    if len(b_list) != len(m_list):
        raise HTTPException(
            status_code=400,
            detail="image_base64 and image_media_type must have the same length",
        )
    if len(b_list) > _MAX_INSPECT_IMAGES:
        raise HTTPException(
            status_code=400,
            detail=f"at most {_MAX_INSPECT_IMAGES} images allowed",
        )
    return list(zip(b_list, m_list))


def _build_contents(req: InspectRequest) -> Any:
    pairs = _normalize_image_pairs(req)
    if not pairs:
        return req.message

    parts: list[Any] = []
    for b64, mt in pairs:
        if not mt:
            raise HTTPException(status_code=400, detail="image_media_type is required for each image")
        try:
            image_bytes = base64.b64decode(b64)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"invalid image_base64: {e}") from e
        if mt.startswith("image/"):
            try:
                image_bytes, mt = resize_thumbnail(image_bytes, 800)
            except Exception:
                pass
        parts.append(types.Part.from_bytes(data=image_bytes, mime_type=mt))
    parts.append(req.message)
    return parts


@router.post("/inspect", response_model=InspectResponse)
async def inspect(req: InspectRequest):
    history = get_active_history()
    guidelines = get_guidelines()
    terms = get_terms()

    if req.mode == "소재검수":
        system_prompt = build_inspect_prompt(history=history, guidelines=guidelines, terms=terms)
        contents = _build_contents(req)
        rules_n = len(history)
    elif req.mode == "히스토리조회":
        system_prompt = build_history_prompt(history=history)
        contents = req.message
        rules_n = len(history)
    elif req.mode == "용어해석":
        system_prompt = build_terms_prompt(terms=terms)
        contents = req.message
        rules_n = len(history)
    elif req.mode == "원본메시지검색":
        fk = req.raw_kind if req.raw_kind in ("feedback", "not_feedback", "bot") else None
        lim = req.raw_limit if req.raw_limit is not None else 100
        lim = min(max(int(lim), 1), 500)
        ord_ = req.raw_order or "desc"
        if ord_ not in ("asc", "desc"):
            ord_ = "desc"
        raw_msgs = get_raw_messages(
            limit=lim,
            offset=0,
            filter_kind=fk,
            q=req.raw_query,
            author=req.raw_author,
            has_files=req.raw_has_files,
            order=ord_,
        )
        parents = [str(m["ts"]) for m in raw_msgs if m.get("ts")]
        thread_map = get_raw_thread_replies_bulk(parents)
        system_prompt = build_raw_messages_prompt(raw_messages=raw_msgs, thread_replies=thread_map)
        contents = req.message
        rules_n = len(raw_msgs) + sum(len(v) for v in thread_map.values())
    elif req.mode == "카피창작":
        copybank = get_copybank(limit=200)
        system_prompt = build_create_copy_prompt(copybank=copybank, guidelines=guidelines, terms=terms)
        contents = req.message
        rules_n = len(copybank)
    else:
        raise HTTPException(status_code=400, detail=f"invalid mode: {req.mode}")

    async with GEMINI_SEMAPHORE:
        feedback = await asyncio.to_thread(inspect_creative, system_prompt, contents)
    return InspectResponse(feedback=feedback, rules_checked=rules_n)


@router.post("/inspect-upload", response_model=InspectResponse)
async def inspect_upload(
    message: str = Form("이 소재를 검수해주세요."),
    mode: str = Form("소재검수"),
    files: list[UploadFile] = File(default_factory=list),
):
    """
    로컬 첨부: multipart. 영상은 ffmpeg로 프레임(JPEG)+오디오(MP3)로 분해 후 Part.from_bytes로 전달.
    이미지는 bytes → Part 직접.
    """
    if mode != "소재검수":
        raise HTTPException(status_code=400, detail="inspect-upload는 소재검수만 지원합니다.")

    file_list = list(files or [])[:_MAX_INSPECT_IMAGES]
    history = get_active_history()
    guidelines = get_guidelines()
    terms = get_terms()
    system_prompt = build_inspect_prompt(history=history, guidelines=guidelines, terms=terms)
    rules_n = len(history)

    parts: list[Any] = []
    video_idx = 0

    for uf in file_list:
        data = await uf.read()
        if not data:
            continue
        mt = (uf.content_type or "application/octet-stream").strip() or "application/octet-stream"
        fname = ((uf.filename or "file").strip() or "file")[:512]

        if mt.startswith("video/"):
            result = await asyncio.to_thread(extract_frames_and_audio, data)
            video_idx += 1
            for frame_data, frame_mt in result["frames"]:
                parts.append(types.Part.from_bytes(data=frame_data, mime_type=frame_mt))
            if result["audio"]:
                audio_data, audio_mt = result["audio"]
                parts.append(types.Part.from_bytes(data=audio_data, mime_type=audio_mt))
            audio_note = (
                "오디오(MP3)도 첨부되어 있습니다."
                if result["audio"]
                else "오디오는 없거나 추출되지 않았습니다."
            )
            parts.append(
                f"### 영상 {video_idx} (파일명: {fname})\n"
                f"위 이미지들은 영상에서 시간 간격으로 샘플링한 프레임입니다. {audio_note} "
                "스크립트를 추출하고 소재를 검수해주세요."
            )
        else:
            if mt.startswith("image/"):
                try:
                    data, mt = await asyncio.to_thread(resize_thumbnail, data, 800)
                except Exception:
                    pass
            parts.append(types.Part.from_bytes(data=data, mime_type=mt))

    if not parts:
        contents: Any = message
    else:
        parts.append(message)
        contents = parts

    async with GEMINI_SEMAPHORE:
        feedback = await asyncio.to_thread(inspect_creative, system_prompt, contents)

    return InspectResponse(feedback=feedback, rules_checked=rules_n)
