from __future__ import annotations

import os
import time
from typing import Any
from urllib.parse import quote

import httpx

FIGMA_API = "https://api.figma.com/v1"


class FigmaRateLimitError(RuntimeError):
    """Figma REST API returned HTTP 429."""

    def __init__(self) -> None:
        super().__init__("Figma API 요청 한도를 초과했습니다. 1분 후 다시 시도해주세요.")


def _token() -> str:
    t = (os.getenv("FIGMA_TOKEN") or "").strip()
    if not t:
        raise RuntimeError("FIGMA_TOKEN is not set in environment")
    return t


def _headers() -> dict[str, str]:
    return {"X-Figma-Token": _token()}


def normalize_figma_node_id(node_id: str) -> str:
    """URL의 node-id(하이픈)를 API용 콜론 형식으로 통일."""
    s = (node_id or "").strip()
    if not s:
        return s
    return s.replace("-", ":")


def _request_json(method: str, url: str, **kwargs: Any) -> httpx.Response:
    h = dict(_headers())
    extra = kwargs.pop("headers", None) or {}
    h.update(extra)
    kwargs["headers"] = h
    kwargs.setdefault("timeout", 60.0)
    with httpx.Client() as client:
        r = client.request(method, url, **kwargs)
    if r.status_code == 429:
        raise FigmaRateLimitError()
    return r


def get_file_info(file_key: str) -> dict[str, Any]:
    """파일 메타데이터 (이름 등). 403 시 권한 오류."""
    fk = (file_key or "").strip()
    if not fk:
        raise ValueError("file_key is required")
    url = f"{FIGMA_API}/files/{quote(fk, safe='')}"
    r = _request_json("GET", url)
    if r.status_code == 403:
        raise PermissionError("해당 Figma 파일에 접근할 수 없습니다. 토큰 소유자에게 파일 공유·권한을 확인하세요.")
    if r.status_code >= 400:
        raise RuntimeError(f"Figma API error {r.status_code}: {r.text[:500]}")
    return r.json()


def _name_suggests_image_file(name: str) -> bool:
    n = (name or "").lower()
    return ".jpg" in n or ".jpeg" in n or ".png" in n


def _has_image_fill(node: dict[str, Any]) -> bool:
    fills = node.get("fills") or []
    for f in fills:
        if not isinstance(f, dict):
            continue
        if f.get("visible") is False:
            continue
        if f.get("type") == "IMAGE":
            return True
    if node.get("imageFills"):
        return True
    return False


def _is_image_candidate_node(node: dict[str, Any]) -> bool:
    """RECTANGLE/FRAME/INSTANCE + 이미지 fill, 또는 이름에 .jpg/.png 등 포함."""
    if _name_suggests_image_file(node.get("name") or ""):
        return True
    ntype = (node.get("type") or "").upper()
    if ntype not in ("RECTANGLE", "FRAME", "INSTANCE"):
        return False
    return _has_image_fill(node)


def _collect_image_nodes(
    node: dict[str, Any] | None,
    out: list[dict[str, str]],
    seen_ids: set[str],
) -> None:
    if not node or not isinstance(node, dict):
        return
    nid = (node.get("id") or "").strip()
    name = (node.get("name") or "").strip() or nid
    if nid and nid not in seen_ids and _is_image_candidate_node(node):
        out.append({"id": nid, "name": name})
        seen_ids.add(nid)
    for ch in node.get("children") or []:
        if isinstance(ch, dict):
            _collect_image_nodes(ch, out, seen_ids)


def get_image_children(file_key: str, node_id: str) -> list[dict[str, str]]:
    """
    GET /v1/files/{key}/nodes?ids=... 로 서브트리를 받아, 이미지 소재로 보이는 노드 id를 수집한다.
    (RECTANGLE/FRAME/INSTANCE + IMAGE fill, 또는 이름에 .jpg/.png 포함)
    문서 순서대로 depth-first. 없으면 빈 리스트 → 호출부에서 프레임 단일 export로 폴백.
    """
    fk = (file_key or "").strip()
    nid = normalize_figma_node_id(node_id)
    if not fk or not nid:
        return []
    url = f"{FIGMA_API}/files/{quote(fk, safe='')}/nodes"
    r = _request_json("GET", url, params={"ids": nid})
    if r.status_code == 403:
        raise PermissionError("해당 Figma 파일에 접근할 수 없습니다. 토큰 소유자에게 파일 공유·권한을 확인하세요.")
    if r.status_code >= 400:
        raise RuntimeError(f"Figma nodes API error {r.status_code}: {r.text[:500]}")
    data = r.json()
    nodes = data.get("nodes") or {}
    entry = nodes.get(nid)
    if entry is None and nid.replace(":", "-") in nodes:
        entry = nodes.get(nid.replace(":", "-"))
    if entry is None and nodes:
        entry = next(iter(nodes.values()), None)
    if not entry:
        return []
    doc = entry.get("document")
    out: list[dict[str, str]] = []
    _collect_image_nodes(doc, out, set())
    return out


_EXPORT_IDS_CHUNK = 20


def export_nodes_as_pngs(file_key: str, node_ids: list[str], scale: int = 2) -> dict[str, str | None]:
    """여러 노드 PNG 내보내기 — 정규화된 id → CDN URL (없으면 None)."""
    fk = (file_key or "").strip()
    if not fk or not node_ids:
        return {}
    norm_ids = [normalize_figma_node_id(x) for x in node_ids if (x or "").strip()]
    if not norm_ids:
        return {}
    result: dict[str, str | None] = {k: None for k in norm_ids}
    url = f"{FIGMA_API}/images/{quote(fk, safe='')}"
    for i in range(0, len(norm_ids), _EXPORT_IDS_CHUNK):
        chunk = norm_ids[i : i + _EXPORT_IDS_CHUNK]
        ids_param = ",".join(chunk)
        r = _request_json("GET", url, params={"ids": ids_param, "format": "png", "scale": str(scale)})
        if r.status_code == 403:
            raise PermissionError("해당 Figma 파일에 접근할 수 없습니다. 토큰 소유자에게 파일 공유·권한을 확인하세요.")
        if r.status_code >= 400:
            raise RuntimeError(f"Figma images API error {r.status_code}: {r.text[:500]}")
        data = r.json()
        images = data.get("images") or {}
        for cid in chunk:
            u = images.get(cid)
            if not u and cid.replace(":", "-") in images:
                u = images.get(cid.replace(":", "-"))
            if not u:
                for k, v in images.items():
                    if k.replace("-", ":") == cid or k == cid:
                        u = v
                        break
            result[cid] = u if u else None
    return result


def export_frame_as_png(file_key: str, node_id: str, scale: int = 2) -> str | None:
    """
    프레임 PNG 내보내기 — 응답의 임시 CDN URL 반환.
    """
    fk = (file_key or "").strip()
    nid = normalize_figma_node_id(node_id)
    if not fk or not nid:
        return None
    m = export_nodes_as_pngs(fk, [nid], scale=scale)
    return m.get(nid)


def download_figma_image(cdn_url: str) -> bytes | None:
    """내보내기 URL에서 PNG 바이트(CDN은 보통 무인증). 실패 시 None."""
    u = (cdn_url or "").strip()
    if not u:
        return None
    try:
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            r = client.get(u)
        if r.status_code == 429:
            time.sleep(min(float(r.headers.get("Retry-After") or "2"), 30.0))
            with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                r = client.get(u)
        if r.status_code >= 400 or not r.content:
            return None
        return r.content
    except Exception:
        return None
