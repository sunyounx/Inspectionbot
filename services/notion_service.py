from __future__ import annotations

import os
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import httpx

_NOTION_VERSION = "2022-06-28"
_MAX_CHARS = 10_000
_UUID_HYPHEN_RE = re.compile(
    r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}",
    re.I,
)

class _PlainHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._title_depth = 0
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.meta_description: str = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t in ("script", "style", "noscript", "svg"):
            self._skip_depth += 1
        if t == "title":
            self._title_depth += 1
        if t == "meta":
            attrs_map = {k.lower(): (v or "") for k, v in attrs}
            name = attrs_map.get("name", "").lower()
            prop = attrs_map.get("property", "").lower()
            if name == "description" or prop == "og:description":
                self.meta_description = attrs_map.get("content", "").strip()

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in ("script", "style", "noscript", "svg") and self._skip_depth:
            self._skip_depth -= 1
        if t == "title" and self._title_depth:
            self._title_depth -= 1

    def handle_data(self, data: str) -> None:
        text = re.sub(r"\s+", " ", data or "").strip()
        if not text:
            return
        if self._title_depth:
            self.title_parts.append(text)
            return
        if not self._skip_depth:
            self.text_parts.append(text)


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


def _is_public_notion_url(url: str) -> bool:
    parsed = urlparse((url or "").strip())
    host = (parsed.netloc or "").lower()
    if parsed.scheme not in ("http", "https"):
        return False
    return host == "notion.so" or host.endswith(".notion.so") or host == "notion.site" or host.endswith(".notion.site")


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


def _raise_for_public_status(resp: httpx.Response, *, context: str) -> None:
    if resp.status_code in (401, 403):
        raise RuntimeError(f"공개 Notion 페이지 접근 권한 오류: 링크 공유 상태를 확인하세요. ({context})")
    if resp.status_code == 404:
        raise RuntimeError(f"공개 Notion 페이지를 찾을 수 없습니다. ({context})")
    if resp.status_code >= 400:
        raise RuntimeError(f"공개 Notion 페이지 읽기 오류 ({resp.status_code}): {context}")


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


def _read_notion_page_api(url: str, token: str) -> str | None:
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


def _read_public_notion_page(url: str) -> str | None:
    if not _is_public_notion_url(url):
        raise RuntimeError("공개 Notion URL만 읽을 수 있습니다.")

    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            resp = client.get(
                url,
                headers={
                    "User-Agent": "Inspectionbot/1.0",
                    "Accept": "text/html,application/xhtml+xml",
                },
            )
            _raise_for_public_status(resp, context=url)
            html = resp.text or ""
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"공개 Notion 페이지 읽기 실패: {e}") from e

    parser = _PlainHTMLParser()
    try:
        parser.feed(html)
    except Exception as e:
        raise RuntimeError(f"공개 Notion HTML 파싱 실패: {e}") from e

    parts: list[str] = []
    title = " ".join(parser.title_parts).strip()
    if title:
        parts.append(title)
    if parser.meta_description:
        parts.append(parser.meta_description)
    for text in parser.text_parts:
        if text not in parts:
            parts.append(text)

    body = "\n".join(parts).strip()
    if not body:
        return None
    if len(body) > _MAX_CHARS:
        body = body[:_MAX_CHARS]
    return body


def read_notion_page(url: str) -> str | None:
    token = _notion_token()
    if token:
        try:
            return _read_notion_page_api(url, token)
        except RuntimeError as api_error:
            try:
                return _read_public_notion_page(url)
            except RuntimeError as public_error:
                raise RuntimeError(f"{api_error}; 공개 링크 읽기도 실패: {public_error}") from public_error
    return _read_public_notion_page(url)
