import os
import re
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


load_dotenv()

_user_cache: dict[str, str] = {}
_USER_MENTION_RE = re.compile(r"<@([A-Z0-9]+)(?:\|([^>]*))?>")


def _user_token() -> str:
    return os.getenv("SLACK_USER_TOKEN", "").strip()


def _client() -> WebClient:
    token = _user_token()
    if not token:
        raise RuntimeError("Missing SLACK_USER_TOKEN in .env")
    return WebClient(token=token)


def download_slack_image(url: str) -> bytes | None:
    """
    Slack 비공개 파일 URL(url_private 등) 다운로드.
    Authorization: Bearer + Cookie: d= 토큰. 실패 시 None.
    """
    u = (url or "").strip()
    token = _user_token()
    if not u or not token:
        return None
    headers = {
        "Authorization": f"Bearer {token}",
        "Cookie": f"d={token}",
    }
    try:
        with httpx.Client(timeout=45.0, follow_redirects=True) as client:
            r = client.get(u, headers=headers)
        if r.status_code >= 400 or not r.content:
            return None
        return r.content
    except Exception:
        return None


def get_user_name(user_id: str) -> str:
    """슬랙 users.info로 표시 이름 조회. 캐시 히트면 API 호출 안 함. 실패 시 user_id 그대로."""
    uid = (user_id or "").strip()
    if not uid:
        return ""
    if uid in _user_cache:
        return _user_cache[uid]
    try:
        client = _client()
        resp = client.users_info(user=uid)
        if not resp.get("ok"):
            _user_cache[uid] = uid
            return uid
        user = resp.get("user") or {}
        prof = user.get("profile") or {}
        name = (
            (user.get("real_name") or "").strip()
            or (prof.get("display_name") or "").strip()
            or (user.get("name") or "").strip()
            or uid
        )
        _user_cache[uid] = name
        return name
    except (SlackApiError, Exception):
        _user_cache[uid] = uid
        return uid


def resolve_mentions(text: str) -> str:
    """<@U099GQDA75Y> 또는 <@U099GQDA75Y|표시이름> → @표시이름 / @실명 형태로 치환."""
    t = text or ""
    if "<@" not in t:
        return t

    def replacer(m):
        uid = m.group(1)
        label = (m.group(2) or "").strip()
        if label:
            return f"@{label}"
        name = get_user_name(uid)
        return f"@{name}"

    return _USER_MENTION_RE.sub(replacer, t)


_SLACK_SUBTEAM_PIPE_RE = re.compile(r"<!subteam\^[A-Z0-9]+\|([^>]+)>")
_SLACK_SUBTEAM_BARE_RE = re.compile(r"<!subteam\^[A-Z0-9]+>")
_SLACK_SPECIAL_RE = re.compile(r"<!(here|channel|everyone|group)(?:\|[^>]*)?>")
_SLACK_LINK_PIPE_RE = re.compile(r"<(https?://[^>|]+)\|([^>]+)>")
_SLACK_LINK_PLAIN_RE = re.compile(r"<(https?://[^>]+)>")
_SLACK_EMOJI_RE = re.compile(r":[a-z0-9_+-]+:", re.I)
_SLACK_BOLD_RE = re.compile(r"\*([^*]+)\*")

_DOC_LINK_RES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"https://docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]+)"), "sheets"),
    (re.compile(r"https://docs\.google\.com/document/d/([a-zA-Z0-9_-]+)"), "docs"),
    (re.compile(r"https://docs\.google\.com/presentation/d/([a-zA-Z0-9_-]+)"), "slides"),
    (re.compile(r"https://drive\.google\.com/file/d/([a-zA-Z0-9_-]+)"), "drive_file"),
    (re.compile(r"https://drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)"), "drive_file"),
]


def clean_slack_markup(text: str) -> str:
    """Slack mrkdwn/HTML 이스케이프·링크·특수멘션·이모지 코드·*굵게* 정리."""
    t = text or ""
    if not t:
        return t
    t = t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    t = _SLACK_SUBTEAM_PIPE_RE.sub(r"@\1", t)
    t = _SLACK_SUBTEAM_BARE_RE.sub("@subteam", t)
    t = _SLACK_SPECIAL_RE.sub(r"@\1", t)
    t = _SLACK_LINK_PIPE_RE.sub(r"\2", t)
    t = _SLACK_LINK_PLAIN_RE.sub(r"\1", t)
    t = _SLACK_EMOJI_RE.sub("", t)
    t = _SLACK_BOLD_RE.sub(r"\1", t)
    return t.strip()


def extract_document_links(text: str) -> list[dict[str, str]]:
    """Google Docs/Sheets/Slides URL에서 file_id·타입 추출 (중복 file_id 제외)."""
    t = text or ""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for pat, kind in _DOC_LINK_RES:
        for m in pat.finditer(t):
            fid = (m.group(1) or "").strip()
            if not fid or fid in seen:
                continue
            seen.add(fid)
            out.append({"type": kind, "file_id": fid, "url": m.group(0).strip()})
    return out


def fetch_new_messages(channel: str, since_ts: str) -> list[dict[str, Any]]:
    """
    conversations.history로 since_ts(초 단위 float string) 이후 메시지 조회.
    Slack API oldest는 inclusive에 가까워 중복이 날 수 있으므로, 호출자는 마지막 ts를 갱신할 때 주의.
    """
    client = _client()
    all_messages: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        try:
            resp = client.conversations_history(channel=channel, oldest=since_ts, limit=200, cursor=cursor)
        except SlackApiError as e:
            raise RuntimeError(f"Slack API error: {e.response.get('error')}") from e
        all_messages.extend(resp.get("messages", []) or [])
        if not resp.get("has_more"):
            break
        cursor = (resp.get("response_metadata") or {}).get("next_cursor") or None
        if not cursor:
            break

    # 최신순 반환이 많아서, 처리 편의상 오래된 순으로 정렬
    return sorted(all_messages, key=lambda m: float(m.get("ts", "0") or "0"))


def fetch_thread_replies(channel: str, thread_ts: str) -> list[dict[str, Any]]:
    """
    conversations.replies로 스레드 댓글 조회.
    첫 메시지는 부모(= thread_ts와 ts가 동일)이므로 제외합니다.
    """
    thread_ts = (thread_ts or "").strip()
    if not thread_ts:
        return []
    client = _client()
    try:
        resp = client.conversations_replies(channel=channel, ts=thread_ts, limit=200)
    except SlackApiError as e:
        raise RuntimeError(f"Slack API error: {e.response.get('error')}") from e

    replies = resp.get("messages", []) or []
    return [m for m in replies if m.get("ts") != thread_ts]


def build_slack_link(channel: str, ts: str) -> Optional[str]:
    """
    원본 메시지 permalink 생성.
    - 성공: chat.getPermalink 사용
    - 실패: None 반환
    """
    client = _client()
    try:
        resp = client.chat_getPermalink(channel=channel, message_ts=ts)
        return resp.get("permalink")
    except SlackApiError:
        return None


def extract_message_text(msg: dict[str, Any]) -> str:
    """
    Slack message payload에서 사람이 입력한 텍스트를 최대한 안전하게 추출.
    (파일/블록 메시지 등은 Phase 2 범위 밖이라 우선 text만 사용)
    """
    return (msg.get("text") or "").strip()


def is_bot_message(msg: dict[str, Any]) -> bool:
    # User token 폴링 기준이라도, 봇이 쓴 메시지가 섞일 수 있어 스킵 규칙 유지
    return bool(msg.get("bot_id")) or (msg.get("subtype") == "bot_message")


_ANGLE_URL_RE = re.compile(r"<(https?://[^>|]+)(?:\|[^>]+)?>")
_BARE_URL_RE = re.compile(r"(https?://[^\s<>()]+)")


def _classify_external_type(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    try:
        host = (urlparse(u).netloc or "").lower()
        path = (urlparse(u).path or "").lower()
    except Exception:
        return ""

    if "docs.google.com" in host and "/spreadsheets" in path:
        return "google_sheets"
    if "docs.google.com" in host and "/document" in path:
        return "google_docs"
    if "docs.google.com" in host and "/presentation" in path:
        return "google_slides"
    if "drive.google.com" in host:
        return "google_drive"
    if "notion.so" in host or "notion.site" in host:
        return "notion"
    if "figma.com" in host:
        return "figma"
    if "files.slack.com" in host:
        return "slack_upload"
    return ""


def _extract_text_urls(text: str) -> list[str]:
    t = (text or "").strip()
    if not t:
        return []

    urls: list[str] = []
    urls.extend(m.group(1) for m in _ANGLE_URL_RE.finditer(t))
    urls.extend(m.group(1) for m in _BARE_URL_RE.finditer(t))

    cleaned: list[str] = []
    for u in urls:
        u = (u or "").strip()
        if not u:
            continue
        # Slack의 link markup이 일부 케이스에서 '>' 없이 들어오면 bare URL 정규식이
        # https://...|표시텍스트 형태까지 먹을 수 있어 URL 부분만 분리
        if "|" in u:
            u = u.split("|", 1)[0].strip()
        # 흔한 문장부호 trailing 제거
        u = u.rstrip(").,;!?]")
        cleaned.append(u)
    return cleaned


def extract_message_files(msg: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Slack message payload에서 파일/링크 정보를 정규화해 반환.
    - msg["files"]: 직접 첨부 파일(슬랙 업로드/외부 파일)
    - msg["attachments"]: unfurl URL preview
    - msg["text"]: <https://...|text> 및 일반 URL
    반환 각 원소는 최소 url을 포함하도록 정규화합니다.
    """
    out: list[dict[str, Any]] = []

    # 1) files
    for f in (msg.get("files") or []) or []:
        if not isinstance(f, dict):
            continue
        url = (f.get("url_private") or f.get("external_url") or "").strip()
        if not url:
            continue
        external_type = (f.get("external_type") or "").strip()
        filetype = (f.get("filetype") or "").strip()
        mimetype = (f.get("mimetype") or "").strip()
        is_external = bool(f.get("is_external")) if f.get("is_external") is not None else False

        # 일부 external file은 filetype/mimetype가 비어있을 수 있어 URL 기반 분류 보강
        inferred = _classify_external_type(url)
        if not external_type and inferred:
            # Slack 업로드 파일도 external_type으로 slack_upload를 붙여 두면
            # (filetype=png/jpg 등과 별개로) 링크 종류 판별이 쉬워짐
            external_type = inferred
        if not filetype and inferred:
            # filetype이 비어있는 external file(예: gdrive/notion) 보강
            filetype = inferred

        out.append(
            {
                "file_id": f.get("id"),
                "name": f.get("name"),
                "filetype": filetype,
                "mimetype": mimetype,
                "url": url,
                "is_external": is_external,
                "external_type": external_type,
                "size": f.get("size"),
            }
        )

    # 2) attachments (unfurl)
    for a in (msg.get("attachments") or []) or []:
        if not isinstance(a, dict):
            continue
        url = (a.get("from_url") or a.get("original_url") or a.get("title_link") or "").strip()
        if not url:
            continue
        external_type = _classify_external_type(url)
        service_name = (a.get("service_name") or "").strip()
        title = (a.get("title") or "").strip()

        out.append(
            {
                "file_id": None,
                "name": title or None,
                "filetype": external_type or (service_name.lower().replace(" ", "_") if service_name else ""),
                "mimetype": "",
                "url": url,
                "is_external": True if external_type and external_type != "slack_upload" else False,
                "external_type": external_type,
                "size": None,
                "title": title,
                "service_name": service_name,
            }
        )

    # 3) text URLs
    text = extract_message_text(msg)
    for url in _extract_text_urls(text):
        external_type = _classify_external_type(url)
        out.append(
            {
                "file_id": None,
                "name": None,
                "filetype": external_type,
                "mimetype": "",
                "url": url,
                "is_external": True if external_type and external_type != "slack_upload" else False,
                "external_type": external_type,
                "size": None,
            }
        )

    # 4) de-dupe by url (files 우선: 메타가 더 풍부)
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in out:
        url = (item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(item)
    return deduped

