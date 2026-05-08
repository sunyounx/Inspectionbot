from __future__ import annotations

import asyncio
import io
import json
import os
import time
import hashlib
import threading
from datetime import date
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.types import FileState

from models.schemas import ConflictCheck, FeedbackClassification, RefinedFeedback
from prompts import classify as classify_prompt
from prompts import conflict as conflict_prompt
from prompts import refine as refine_prompt
from prompts import refine_with_doc as refine_with_doc_prompt


load_dotenv()

_REFINED_CATEGORY_ENUM = ["크리에이티브", "프로모션", "CRM", "브랜딩", "퍼포먼스", "기타", "미분류"]

_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
if not _API_KEY:
    raise RuntimeError("Missing GEMINI_API_KEY in .env")

client = genai.Client(api_key=_API_KEY)

MODEL = "gemini-2.5-flash"

# Gemini generate_content 동시 호출 상한 (Drive/Figma 검수, 승인 적재 등 공통)
GEMINI_SEMAPHORE = asyncio.Semaphore(10)

# ---- system prompt cache (CachedContent) ----
# 모델별로 캐시를 분리한다. key=(model, prompt_hash), value=(cache_obj, expires_at)
_system_caches: dict[tuple[str, str], tuple[Any, float]] = {}
_system_cache_lock = threading.Lock()

# ---- JSON schema for parallel inspect_one ----
INSPECT_ONE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "file_name": {"type": "string"},
        "satisfied": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"item": {"type": "string"}, "detail": {"type": "string"}},
                "required": ["item", "detail"],
            },
        },
        "check_needed": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item": {"type": "string"},
                    "detail": {"type": "string"},
                    "suggestion": {"type": "string"},
                },
                "required": ["item", "detail", "suggestion"],
            },
        },
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item": {"type": "string"},
                    "detail": {"type": "string"},
                    "suggestion": {"type": "string"},
                },
                "required": ["item", "detail"],
            },
        },
        "compliance": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item": {"type": "string"},
                    "severity": {"type": "string", "enum": ["ok", "warning", "violation"]},
                    "detail": {"type": "string"},
                    "alternative": {"type": "string"},
                },
                "required": ["item", "severity", "detail"],
            },
        },
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"detail": {"type": "string"}},
                "required": ["detail"],
            },
        },
    },
    "required": ["file_name", "satisfied", "check_needed", "issues", "compliance", "suggestions"],
}


def invalidate_system_cache() -> None:
    """히스토리/가이드라인 변경 시 호출하여 시스템 프롬프트 캐시를 무효화합니다."""
    with _system_cache_lock:
        _system_caches.clear()


def _get_or_create_cache(system_prompt: str, *, model: str = MODEL) -> str | None:
    """시스템 프롬프트 캐시 생성/재사용. TTL 1시간(55분마다 갱신). 실패 시 None.
    모델별로 슬롯을 분리하여 Flash/Pro 등 다른 모델 캐시가 충돌하지 않도록 한다."""
    now = time.time()
    prompt_hash = hashlib.sha256((system_prompt or "").encode("utf-8")).hexdigest()
    key = (model, prompt_hash)
    with _system_cache_lock:
        existing = _system_caches.get(key)
        if existing:
            cache_obj, expires_at = existing
            if now < expires_at and getattr(cache_obj, "name", None):
                print(f"[system_cache] HIT ({model}): {cache_obj.name}", flush=True)
                return str(cache_obj.name)

        try:
            cache_obj = client.caches.create(
                model=model,
                config=types.CreateCachedContentConfig(
                    system_instruction=system_prompt,
                    ttl="3600s",
                ),
            )
            print(f"[system_cache] CREATED ({model}): {cache_obj.name}", flush=True)
            _system_caches[key] = (cache_obj, now + 3300)  # 55분
            return str(getattr(cache_obj, "name", "") or "") or None
        except Exception as e:
            # 캐시 API 미지원/권한/네트워크 등으로 실패하면 캐시 없이 진행
            print(f"[system_cache] FAILED ({model}): {e}", flush=True)
            _system_caches.pop(key, None)
            return None


def classify_feedback(text: str) -> FeedbackClassification:
    response_schema = {
        "type": "object",
        "properties": {
            "is_feedback": {"type": "boolean"},
            "confidence": {"type": "number"},
            "reason": {"type": "string"},
        },
        "required": ["is_feedback", "confidence", "reason"],
    }

    resp = client.models.generate_content(
        model=MODEL,
        contents=classify_prompt.build_contents(text),
        config=types.GenerateContentConfig(
            system_instruction=classify_prompt.SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=response_schema,
        ),
    )
    return FeedbackClassification.model_validate_json(resp.text)


def refine_feedback(text: str) -> RefinedFeedback:
    response_schema = {
        "type": "object",
        "properties": {
            "date": {"type": "string"},
            "topic": {"type": "string"},
            "summary": {"type": "string"},
            "scope": {"type": "string", "enum": ["영상", "이미지DA", "카피", "전체"]},
            "type": {"type": "string", "enum": ["방향성", "규칙"]},
            "original_quote": {"type": "string"},
            "category": {"type": "string", "enum": _REFINED_CATEGORY_ENUM},
        },
        "required": ["date", "topic", "summary", "scope", "type", "original_quote", "category"],
    }

    today = date.today().isoformat()
    resp = client.models.generate_content(
        model=MODEL,
        contents=refine_prompt.build_contents(text),
        config=types.GenerateContentConfig(
            system_instruction=refine_prompt.build_system_prompt(today=today),
            response_mime_type="application/json",
            response_schema=response_schema,
        ),
    )
    return RefinedFeedback.model_validate_json(resp.text)


def refine_with_document(text: str, doc_content: str | None) -> RefinedFeedback:
    """doc_content가 있으면 문서 포함 프롬프트, 없으면 기본 refine와 동일."""
    response_schema = {
        "type": "object",
        "properties": {
            "date": {"type": "string"},
            "topic": {"type": "string"},
            "summary": {"type": "string"},
            "scope": {"type": "string", "enum": ["영상", "이미지DA", "카피", "전체"]},
            "type": {"type": "string", "enum": ["방향성", "규칙"]},
            "original_quote": {"type": "string"},
            "category": {"type": "string", "enum": _REFINED_CATEGORY_ENUM},
        },
        "required": ["date", "topic", "summary", "scope", "type", "original_quote", "category"],
    }
    today = date.today().isoformat()
    dc = (doc_content or "").strip()
    if dc:
        system_instruction = refine_with_doc_prompt.build_system_prompt(today=today)
        contents = refine_with_doc_prompt.build_contents(text or "", dc)
    else:
        system_instruction = refine_prompt.build_system_prompt(today=today)
        contents = refine_prompt.build_contents(text or "")

    resp = client.models.generate_content(
        model=MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=response_schema,
        ),
    )
    return RefinedFeedback.model_validate_json(resp.text)


def check_conflict(new_item: dict[str, Any], existing_item: dict[str, Any]) -> ConflictCheck:
    response_schema = {
        "type": "object",
        "properties": {
            "conflicts": {"type": "boolean"},
            "explanation": {"type": "string"},
            "recommendation": {
                "type": "string",
                "enum": ["replace_old", "keep_both", "keep_old"],
            },
        },
        "required": ["conflicts", "explanation", "recommendation"],
    }

    existing_text = existing_item.get("summary") or existing_item.get("original_quote") or ""
    new_text = new_item.get("summary") or new_item.get("original_quote") or ""
    contents = conflict_prompt.build_contents(existing_text=existing_text, new_text=new_text)

    resp = client.models.generate_content(
        model=MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=conflict_prompt.SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=response_schema,
        ),
    )
    return ConflictCheck.model_validate_json(resp.text)


def inspect_creative(system_prompt: str, contents: Any, *, model: str = MODEL) -> str:
    """
    Inspect a creative using free-form text output.
    contents는 str 또는 google.genai.types.Part 리스트 등을 받을 수 있습니다.
    model을 지정하면 해당 모델로 호출하고 캐시도 모델별로 분리됩니다.
    """
    cache_name = _get_or_create_cache(system_prompt, model=model)
    if cache_name:
        resp = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(cached_content=cache_name),
        )
    else:
        resp = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(system_instruction=system_prompt),
        )
    return resp.text


def inspect_creative_json(system_prompt: str, contents: Any) -> dict[str, Any]:
    """JSON 스키마 강제 응답. 병렬 개별 이미지 검수용."""
    cache_name = _get_or_create_cache(system_prompt)
    base_cfg = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=INSPECT_ONE_SCHEMA,
    )
    try:
        if cache_name:
            cfg = types.GenerateContentConfig(
                cached_content=cache_name,
                response_mime_type="application/json",
                response_schema=INSPECT_ONE_SCHEMA,
            )
        else:
            cfg = types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=INSPECT_ONE_SCHEMA,
            )
        resp = client.models.generate_content(model=MODEL, contents=contents, config=cfg)
    except Exception as e:
        # cached_content + schema 조합이 안 되는 환경일 수 있어 캐시 없이 재시도
        if cache_name:
            print(f"[inspect_one_json] retry without cache: {e}", flush=True)
            resp = client.models.generate_content(
                model=MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    response_schema=INSPECT_ONE_SCHEMA,
                ),
            )
        else:
            raise

    raw = (resp.text or "").strip()
    try:
        data = json.loads(raw)
    except Exception as e:
        raise RuntimeError(f"inspect_creative_json parse failed: {e}; raw={raw[:800]}") from e
    if not isinstance(data, dict):
        raise RuntimeError(f"inspect_creative_json expected object; got {type(data)}")
    return data


_MAX_FILE_PROCESS_WAIT_ROUNDS = 300  # ~10분 (2초 * 300)


def _file_is_processing(f: types.File) -> bool:
    s = f.state
    return s == FileState.PROCESSING or str(s).endswith("PROCESSING")


def upload_video_to_gemini(data: bytes, mime_type: str, display_name: str) -> types.File:
    """Gemini File API로 영상 업로드 → 처리 완료까지 대기 후 File 반환."""
    buf = io.BytesIO(data)
    f = client.files.upload(
        file=buf,
        config=types.UploadFileConfig(
            mime_type=mime_type,
            display_name=display_name[:512],
        ),
    )
    rounds = 0
    while _file_is_processing(f) and rounds < _MAX_FILE_PROCESS_WAIT_ROUNDS:
        time.sleep(2)
        f = client.files.get(name=f.name)
        rounds += 1
    if _file_is_processing(f):
        raise RuntimeError("Gemini 파일 처리 시간 초과(PROCESSING 상태가 계속됨)")
    if f.state == FileState.FAILED:
        err = getattr(f, "error", None)
        raise RuntimeError(f"Gemini 파일 처리 실패: {err}")
    return f


def delete_gemini_file_safe(name: str | None) -> None:
    """검수 완료 후 업로드 파일 삭제. 실패는 무시."""
    n = (name or "").strip()
    if not n:
        return
    try:
        client.files.delete(name=n)
    except Exception:
        pass


def extract_video_script(file_ref: types.File) -> str:
    """영상에서 대사·자막·나레이션·화면 텍스트 추출."""
    resp = client.models.generate_content(
        model=MODEL,
        contents=[
            file_ref,
            "이 영상의 모든 대사, 자막, 나레이션, 화면에 보이는 텍스트를 시간순으로 추출해주세요. "
            "없으면 빈 응답 대신 한 줄로 '대사/자막이 감지되지 않았습니다'라고 적어주세요.",
        ],
    )
    return (resp.text or "").strip()

