from __future__ import annotations

import os
import threading

_MAX_CHARS = 10_000
_MIN_BODY_LEN = 50
_LOCK = threading.Lock()
_PLAYWRIGHT = None
_BROWSER = None

_SELECTORS = (
    "[data-block-id]",
    "main",
    "article",
    ".notion-page-content",
)


def _timeout_ms() -> int:
    try:
        return max(3000, int(os.getenv("NOTION_PLAYWRIGHT_TIMEOUT_MS", "8000")))
    except ValueError:
        return 8000


def _scroll_enabled() -> bool:
    return (os.getenv("NOTION_PLAYWRIGHT_SCROLL", "1") or "1").strip() not in (
        "0",
        "false",
        "no",
    )


def start_playwright_pool() -> None:
    global _PLAYWRIGHT, _BROWSER
    with _LOCK:
        if _BROWSER is not None:
            return
        from playwright.sync_api import sync_playwright

        _PLAYWRIGHT = sync_playwright().start()
        _BROWSER = _PLAYWRIGHT.chromium.launch(headless=True)
        print("[notion-playwright] pool started", flush=True)


def stop_playwright_pool() -> None:
    global _PLAYWRIGHT, _BROWSER
    with _LOCK:
        if _BROWSER is not None:
            _BROWSER.close()
            _BROWSER = None
        if _PLAYWRIGHT is not None:
            _PLAYWRIGHT.stop()
            _PLAYWRIGHT = None
        print("[notion-playwright] pool stopped", flush=True)


def _extract_page_text(page) -> str:
    for sel in _SELECTORS:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="attached", timeout=3000)
            text = (loc.inner_text() or "").strip()
            if text:
                return text
        except Exception:
            continue
    return (page.locator("body").inner_text() or "").strip()


def scrape_public_notion_page(url: str) -> str:
    """Playwright로 Notion URL 본문 추출. 풀은 start_playwright_pool() 후 사용."""
    u = (url or "").strip()
    if not u:
        raise RuntimeError("Notion URL이 비어 있습니다.")

    with _LOCK:
        if _BROWSER is None:
            start_playwright_pool()
        browser = _BROWSER

    timeout = _timeout_ms()
    page = browser.new_page()
    try:
        page.goto(u, wait_until="domcontentloaded", timeout=timeout)
        if _scroll_enabled():
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(500)
            except Exception:
                pass

        body = _extract_page_text(page)
        if len(body) < _MIN_BODY_LEN:
            raise RuntimeError(
                "Notion 페이지 본문을 읽을 수 없습니다. "
                "비공개·로그인 필요 페이지이거나 integration 공유가 필요할 수 있습니다."
            )
        if len(body) > _MAX_CHARS:
            body = body[:_MAX_CHARS]
        return body
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Notion Playwright 읽기 실패: {e}") from e
    finally:
        page.close()
