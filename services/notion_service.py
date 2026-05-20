from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx

_NOTION_VERSION = "2022-06-28"
_MAX_CHARS = 10_000
_UUID_HYPHEN_RE = re.compile(
    r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}",
    re.I,
)


def extract_page_id(url: str) -> str:
    """path 마지막 segment에서만 page id 추출 (query/fragment의 UUID는 무시)."""
    u = (url or "").strip()
    if not u:
        raise RuntimeError("Notion URL에서 page id를 추출할 수 없습니다.")

    parsed = urlparse(u)
    segments = [s for s in (parsed.path or "").split("/") if s]
    if not segments:
        raise RuntimeError("Notion URL에서 page id를 추출할 수 없습니다.")

    last = segments[-1].split("?")[0].split("#")[0]
    m = _UUID_HYPHEN_RE.search(last)
    if m:
        return m.group(0).replace("-", "").lower()
    compact = last.replace("-", "")
    tail = re.search(r"([a-f0-9]{32})$", compact, re.I)
    if tail:
        return tail.group(1).lower()

    raise RuntimeError("Notion URL에서 page id를 추출할 수 없습니다.")


def _notion_token() -> str:
    return os.getenv("NOTION_API_TOKEN", "").strip()


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": _NOTION_VERSION,
    }


def _api_id(page_id: str) -> str:
    p = page_id.replace("-", "").lower()
    if len(p) != 32:
        raise RuntimeError("Notion URL에서 page id를 추출할 수 없습니다.")
    return f"{p[:8]}-{p[8:12]}-{p[12:16]}-{p[16:20]}-{p[20:]}"


def _rich_text_to_plain(rich_text: list[Any] | None) -> str:
    parts: list[str] = []
    for rt in rich_text or []:
        if not isinstance(rt, dict):
            continue
        t = rt.get("plain_text")
        if not t:
            text_obj = rt.get("text")
            if isinstance(text_obj, dict):
                t = text_obj.get("content")
        if t:
            parts.append(str(t))
    return "".join(parts)


def _block_text(block: dict[str, Any]) -> str:
    btype = (block.get("type") or "").strip()
    payload = block.get(btype)
    if not isinstance(payload, dict):
        return ""

    if btype in (
        "paragraph",
        "heading_1",
        "heading_2",
        "heading_3",
        "bulleted_list_item",
        "numbered_list_item",
        "to_do",
        "toggle",
        "quote",
        "callout",
    ):
        return _rich_text_to_plain(payload.get("rich_text"))

    if btype == "code":
        lang = (payload.get("language") or "").strip()
        body = _rich_text_to_plain(payload.get("rich_text"))
        if lang and body:
            return f"[{lang}]\n{body}"
        return body

    if btype == "table_row":
        cells = payload.get("cells") or []
        row_parts: list[str] = []
        for cell in cells:
            if isinstance(cell, list):
                row_parts.append(_rich_text_to_plain(cell))
        return " | ".join(p for p in row_parts if p)

    return ""


def _raise_for_status(resp: httpx.Response, *, context: str) -> None:
    if resp.status_code in (401, 403):
        raise RuntimeError(
            f"Notion 권한 오류: integration에 페이지가 공유되었는지, NOTION_API_TOKEN이 유효한지 확인하세요. ({context})"
        )
    if resp.status_code == 404:
        raise RuntimeError(f"Notion 페이지를 찾을 수 없습니다. ({context})")
    if resp.status_code >= 400:
        detail = ""
        try:
            detail = str(resp.json())
        except Exception:
            detail = resp.text[:200]
        raise RuntimeError(f"Notion API 오류 ({resp.status_code}): {detail}")


def _get_json(
    client: httpx.Client,
    path: str,
    token: str,
    *,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    resp = client.get(
        f"https://api.notion.com/v1{path}",
        headers=_headers(token),
        params=params,
    )
    _raise_for_status(resp, context=path)
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"Notion API 응답 형식 오류: {path}")
    return data


def _collect_blocks(
    client: httpx.Client,
    block_id: str,
    token: str,
    lines: list[str],
    total_chars: int,
) -> int:
    cursor: str | None = None
    while total_chars < _MAX_CHARS:
        params: dict[str, str] = {"page_size": "100"}
        if cursor:
            params["start_cursor"] = cursor
        data = _get_json(client, f"/blocks/{block_id}/children", token, params=params)
        for block in data.get("results") or []:
            if not isinstance(block, dict):
                continue
            text = _block_text(block).strip()
            if text:
                lines.append(text)
                total_chars += len(text) + 1
                if total_chars >= _MAX_CHARS:
                    return total_chars
            if block.get("has_children"):
                child_id = (block.get("id") or "").strip()
                if child_id:
                    total_chars = _collect_blocks(client, child_id, token, lines, total_chars)
                    if total_chars >= _MAX_CHARS:
                        return total_chars
        if not data.get("has_more"):
            break
        cursor = (data.get("next_cursor") or "").strip() or None
        if not cursor:
            break
    return total_chars


def read_notion_page(url: str) -> str | None:
    """Notion 공식 API로만 페이지 본문을 읽는다. integration 공유 + NOTION_API_TOKEN 필수."""
    token = _notion_token()
    if not token:
        raise RuntimeError(
            "NOTION_API_TOKEN이 설정되지 않았습니다. .env에 토큰을 추가한 뒤 다시 시도하세요."
        )

    page_id = extract_page_id(url)
    api_id = _api_id(page_id)

    try:
        with httpx.Client(timeout=30.0) as client:
            _get_json(client, f"/pages/{api_id}", token)
            lines: list[str] = []
            _collect_blocks(client, api_id, token, lines, 0)
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Notion 페이지 읽기 실패: {e}") from e

    body = "\n".join(lines).strip()
    if not body:
        return None
    if len(body) > _MAX_CHARS:
        body = body[:_MAX_CHARS]
    return body
