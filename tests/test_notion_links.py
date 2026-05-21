import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.notion_service import (
    NotionNotFoundError,
    NotionPermissionError,
    extract_page_id,
    read_notion_page,
    _should_try_playwright,
)
from services.slack_service import extract_notion_links


class TestExtractNotionLinks(unittest.TestCase):
    def test_slack_markup(self) -> None:
        text = "<https://www.notion.so/ws/Page-abc123def4567890abcdef1234567890|title>"
        links = extract_notion_links(text)
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["type"], "notion")
        self.assertIn("notion.so", links[0]["url"])

    def test_bare_notion_so(self) -> None:
        url = "https://www.notion.so/ws/Page-abc123def4567890abcdef1234567890"
        links = extract_notion_links(f"see {url}")
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["url"], url)

    def test_notion_site(self) -> None:
        url = "https://workspace.notion.site/Page-abc123def4567890abcdef1234567890"
        links = extract_notion_links(url)
        self.assertEqual(len(links), 1)
        self.assertIn("notion.site", links[0]["url"])

    def test_trailing_punctuation(self) -> None:
        url = "https://www.notion.so/ws/Page-abc123def4567890abcdef1234567890"
        links = extract_notion_links(f"({url}).")
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["url"], url)

    def test_duplicate_removed(self) -> None:
        url = "https://www.notion.so/ws/Page-abc123def4567890abcdef1234567890"
        links = extract_notion_links(f"{url} and {url}")
        self.assertEqual(len(links), 1)


class TestExtractPageId(unittest.TestCase):
    _ID = "abc123def4567890abcdef1234567890"
    _UUID = "abc123de-f456-7890-abcd-ef1234567890"

    def test_slug_with_32_hex(self) -> None:
        pid = extract_page_id(f"https://www.notion.so/ws/Page-Title-{self._ID}")
        self.assertEqual(pid, self._ID)

    def test_bare_32_hex_path(self) -> None:
        pid = extract_page_id(f"https://www.notion.so/{self._ID}")
        self.assertEqual(pid, self._ID)

    def test_hyphen_uuid(self) -> None:
        pid = extract_page_id(f"https://www.notion.so/ws/Page-{self._UUID}?v=1#x")
        self.assertEqual(pid, self._UUID.replace("-", ""))

    def test_ignores_uuid_in_query_not_path(self) -> None:
        other = "fedcba0987654321fedcba0987654321"
        pid = extract_page_id(
            f"https://www.notion.so/ws/Page-{self._ID}?p={other}"
        )
        self.assertEqual(pid, self._ID)

    def test_invalid_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            extract_page_id("https://example.com/no-id")


class TestReadNotionPage(unittest.TestCase):
    _ID = "abc123def4567890abcdef1234567890"
    _URL = f"https://www.notion.so/ws/Page-{_ID}"
    _API_ID = "abc123de-f456-7890-abcd-ef1234567890"

    def _mock_client(self, page_resp: dict, blocks_pages: list[dict]) -> MagicMock:
        client = MagicMock()
        responses: list[MagicMock] = []

        page_mock = MagicMock()
        page_mock.status_code = 200
        page_mock.json.return_value = page_resp
        responses.append(page_mock)

        for blocks in blocks_pages:
            blocks_mock = MagicMock()
            blocks_mock.status_code = 200
            blocks_mock.json.return_value = blocks
            responses.append(blocks_mock)

        client.get.side_effect = responses
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        return client

    @patch.dict("os.environ", {"NOTION_API_TOKEN": "secret_test"})
    @patch("services.notion_service.httpx.Client")
    def test_reads_paragraph_and_heading(self, mock_client_cls: MagicMock) -> None:
        blocks = {
            "results": [
                {
                    "id": "b1",
                    "type": "paragraph",
                    "has_children": False,
                    "paragraph": {"rich_text": [{"plain_text": "hello"}]},
                },
                {
                    "id": "b2",
                    "type": "heading_1",
                    "has_children": False,
                    "heading_1": {"rich_text": [{"plain_text": "Title"}]},
                },
            ],
            "has_more": False,
        }
        mock_client_cls.return_value = self._mock_client({"id": self._API_ID}, [blocks])

        text = read_notion_page(self._URL)
        self.assertEqual(text, "hello\nTitle")

        first_call = mock_client_cls.return_value.get.call_args_list[0]
        self.assertEqual(first_call.kwargs["headers"]["Notion-Version"], "2022-06-28")

    @patch.dict("os.environ", {"NOTION_API_TOKEN": "secret_test"})
    @patch("services.notion_service.httpx.Client")
    def test_pagination(self, mock_client_cls: MagicMock) -> None:
        page1 = {
            "results": [
                {
                    "id": "b1",
                    "type": "paragraph",
                    "has_children": False,
                    "paragraph": {"rich_text": [{"plain_text": "a"}]},
                }
            ],
            "has_more": True,
            "next_cursor": "cur1",
        }
        page2 = {
            "results": [
                {
                    "id": "b2",
                    "type": "paragraph",
                    "has_children": False,
                    "paragraph": {"rich_text": [{"plain_text": "b"}]},
                }
            ],
            "has_more": False,
        }
        client = MagicMock()
        page_mock = MagicMock(status_code=200)
        page_mock.json.return_value = {"id": self._API_ID}
        b1 = MagicMock(status_code=200)
        b1.json.return_value = page1
        b2 = MagicMock(status_code=200)
        b2.json.return_value = page2
        client.get.side_effect = [page_mock, b1, b2]
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        mock_client_cls.return_value = client

        text = read_notion_page(self._URL)
        self.assertEqual(text, "a\nb")

    @patch.dict("os.environ", {"NOTION_API_TOKEN": "secret_test"})
    @patch("services.notion_service.httpx.Client")
    def test_nested_children(self, mock_client_cls: MagicMock) -> None:
        parent_blocks = {
            "results": [
                {
                    "id": "parent",
                    "type": "toggle",
                    "has_children": True,
                    "toggle": {"rich_text": [{"plain_text": "toggle"}]},
                }
            ],
            "has_more": False,
        }
        child_blocks = {
            "results": [
                {
                    "id": "child",
                    "type": "paragraph",
                    "has_children": False,
                    "paragraph": {"rich_text": [{"plain_text": "nested"}]},
                }
            ],
            "has_more": False,
        }
        client = MagicMock()
        page_mock = MagicMock(status_code=200)
        page_mock.json.return_value = {"id": self._API_ID}
        p = MagicMock(status_code=200)
        p.json.return_value = parent_blocks
        c = MagicMock(status_code=200)
        c.json.return_value = child_blocks
        client.get.side_effect = [page_mock, p, c]
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        mock_client_cls.return_value = client

        text = read_notion_page(self._URL)
        self.assertEqual(text, "toggle\nnested")

    @patch.dict("os.environ", {"NOTION_API_TOKEN": "secret_test"})
    @patch("services.notion_service.httpx.Client")
    def test_empty_page_returns_none(self, mock_client_cls: MagicMock) -> None:
        empty_blocks = {"results": [], "has_more": False}
        mock_client_cls.return_value = self._mock_client({"id": self._API_ID}, [empty_blocks])
        self.assertIsNone(read_notion_page(self._URL))

    @patch.dict("os.environ", {"NOTION_API_TOKEN": "secret_test"})
    @patch("services.notion_service._read_notion_page_playwright")
    @patch("services.notion_service.httpx.Client")
    def test_403_raises_after_playwright_fails(
        self, mock_client_cls: MagicMock, mock_pw: MagicMock
    ) -> None:
        client = MagicMock()
        resp = MagicMock(status_code=403)
        resp.json.return_value = {"message": "forbidden"}
        client.get.return_value = resp
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        mock_client_cls.return_value = client
        mock_pw.side_effect = RuntimeError("pw fail")

        with self.assertRaises(RuntimeError) as ctx:
            read_notion_page(self._URL)
        self.assertIn("권한", str(ctx.exception))
        self.assertIn("pw fail", str(ctx.exception))
        mock_pw.assert_called_once_with(self._URL)

    @patch.dict("os.environ", {}, clear=True)
    @patch("services.notion_service._read_notion_page_playwright")
    def test_no_token_uses_playwright(self, mock_pw: MagicMock) -> None:
        mock_pw.return_value = "playwright body"
        text = read_notion_page(self._URL)
        self.assertEqual(text, "playwright body")
        mock_pw.assert_called_once_with(self._URL)

    @patch.dict("os.environ", {"NOTION_API_TOKEN": "secret_test"})
    @patch("services.notion_service._read_notion_page_playwright")
    @patch("services.notion_service.httpx.Client")
    def test_api_403_falls_back_to_playwright(
        self, mock_client_cls: MagicMock, mock_pw: MagicMock
    ) -> None:
        client = MagicMock()
        resp = MagicMock(status_code=403)
        resp.json.return_value = {"message": "forbidden"}
        client.get.return_value = resp
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        mock_client_cls.return_value = client
        mock_pw.return_value = "Playwright body text here with enough length for validation"

        text = read_notion_page(self._URL)
        self.assertIn("Playwright", text)
        mock_pw.assert_called_once_with(self._URL)

    def test_should_try_playwright_types(self) -> None:
        self.assertTrue(_should_try_playwright(NotionPermissionError("x")))
        self.assertTrue(_should_try_playwright(NotionNotFoundError("x")))
        self.assertFalse(_should_try_playwright(RuntimeError("network")))


class TestResolveDocContent(unittest.IsolatedAsyncioTestCase):
    @patch("routers.approval.read_notion_page")
    @patch("routers.approval.read_workspace_document")
    async def test_google_none_fails(
        self, mock_read_doc: MagicMock, mock_read_notion: MagicMock
    ) -> None:
        from routers.approval import _resolve_doc_content

        mock_read_doc.return_value = None
        pending = {"full_text": "https://docs.google.com/document/d/abc123/edit"}
        with self.assertRaises(RuntimeError):
            await _resolve_doc_content(pending, "token")

    @patch("routers.approval.read_notion_page")
    @patch("routers.approval.read_workspace_document")
    async def test_google_exception_fails(
        self, mock_read_doc: MagicMock, mock_read_notion: MagicMock
    ) -> None:
        from routers.approval import _resolve_doc_content

        mock_read_doc.side_effect = ValueError("boom")
        pending = {"full_text": "https://docs.google.com/document/d/abc123/edit"}
        with self.assertRaises(RuntimeError):
            await _resolve_doc_content(pending, "token")

    @patch("routers.approval.read_notion_page")
    @patch("routers.approval.read_workspace_document")
    async def test_notion_exception_fails(
        self, mock_read_doc: MagicMock, mock_read_notion: MagicMock
    ) -> None:
        from routers.approval import _resolve_doc_content

        mock_read_notion.side_effect = RuntimeError("notion fail")
        pending = {
            "full_text": "https://www.notion.so/ws/Page-abc123def4567890abcdef1234567890",
        }
        with self.assertRaises(RuntimeError):
            await _resolve_doc_content(pending, None)

    @patch("routers.approval.read_notion_page")
    @patch("routers.approval.read_workspace_document")
    async def test_both_docs_merged(
        self, mock_read_doc: MagicMock, mock_read_notion: MagicMock
    ) -> None:
        from routers.approval import _resolve_doc_content

        mock_read_doc.return_value = "google body"
        mock_read_notion.return_value = "notion body"
        g_url = "https://docs.google.com/document/d/abc123def4567890abcdef12345678/edit"
        n_url = "https://www.notion.so/ws/Page-abc123def4567890abcdef1234567890"
        doc_content = await _resolve_doc_content(
            {"full_text": f"{g_url}\n{n_url}"}, "token"
        )
        self.assertIn("google body", doc_content or "")
        self.assertIn("notion body", doc_content or "")
        self.assertIn("---", doc_content or "")


class TestInsertRefinedHistory(unittest.IsolatedAsyncioTestCase):
    @patch("routers.approval.refine_with_document")
    @patch("routers.approval.insert_history")
    @patch("routers.approval.invalidate_system_cache")
    async def test_no_links_proceeds(
        self,
        mock_invalidate: MagicMock,
        mock_insert: MagicMock,
        mock_refine: MagicMock,
    ) -> None:
        from routers.approval import _insert_refined_history
        from services.gemini_service import RefinedFeedback

        mock_refine.return_value = RefinedFeedback(
            date="2026-01-01",
            topic="t",
            summary="s",
            scope="전체",
            type="규칙",
            original_quote="q",
            category="크리에이티브",
        )
        mock_insert.return_value = 1

        await _insert_refined_history({"full_text": "plain text"}, doc_content=None)

        self.assertIsNone(mock_refine.call_args[0][1])
        mock_insert.assert_called_once()


class TestCancelApproval(unittest.TestCase):
    @patch("routers.approval.cancel_pending_approval")
    @patch("routers.approval.invalidate_system_cache")
    @patch("routers.approval.get_pending_approval_by_id")
    def test_cancel_ok(self, mock_get, _mock_inv, mock_cancel) -> None:
        from routers.approval import cancel_approval

        mock_get.return_value = {"id": 7, "status": "승인됨"}
        mock_cancel.return_value = {
            "ok": True,
            "pending_status": "대기중",
            "deleted_history_id": 99,
            "restored_old_history_id": None,
        }

        result = cancel_approval(7)
        self.assertTrue(result["ok"])
        self.assertEqual(result["deleted_history_id"], 99)
        mock_cancel.assert_called_once_with(7)

    @patch("routers.approval.get_pending_approval_by_id")
    def test_cancel_rejects_non_approved(self, mock_get) -> None:
        from fastapi import HTTPException

        from routers.approval import cancel_approval

        mock_get.return_value = {"id": 7, "status": "대기중"}
        with self.assertRaises(HTTPException) as ctx:
            cancel_approval(7)
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
