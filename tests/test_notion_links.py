import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.notion_service import extract_page_id, read_notion_page
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
    @patch("services.notion_service.httpx.Client")
    def test_403_raises(self, mock_client_cls: MagicMock) -> None:
        client = MagicMock()
        resp = MagicMock(status_code=403)
        resp.json.return_value = {"message": "forbidden"}
        client.get.return_value = resp
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        mock_client_cls.return_value = client

        with self.assertRaises(RuntimeError) as ctx:
            read_notion_page(self._URL)
        self.assertIn("권한", str(ctx.exception))

    @patch.dict("os.environ", {}, clear=True)
    @patch("services.notion_service.httpx.Client")
    def test_public_url_without_token_reads_html(self, mock_client_cls: MagicMock) -> None:
        html = """
        <html>
          <head>
            <title>Campaign Rule</title>
            <meta name="description" content="Main description">
            <script>ignore me</script>
          </head>
          <body><main><h1>Headline</h1><p>Body text</p></main></body>
        </html>
        """
        client = MagicMock()
        resp = MagicMock(status_code=200)
        resp.text = html
        client.get.return_value = resp
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        mock_client_cls.return_value = client

        text = read_notion_page(self._URL)

        self.assertIn("Campaign Rule", text)
        self.assertIn("Main description", text)
        self.assertIn("Headline", text)
        self.assertIn("Body text", text)
        self.assertNotIn("ignore me", text)

    @patch.dict("os.environ", {}, clear=True)
    @patch("services.notion_service.httpx.Client")
    def test_public_url_403_raises(self, mock_client_cls: MagicMock) -> None:
        client = MagicMock()
        resp = MagicMock(status_code=403)
        resp.text = "forbidden"
        client.get.return_value = resp
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        mock_client_cls.return_value = client

        with self.assertRaises(RuntimeError) as ctx:
            read_notion_page(self._URL)
        self.assertIn("접근 권한", str(ctx.exception))

    @patch.dict("os.environ", {"NOTION_API_TOKEN": "secret_test"})
    @patch("services.notion_service.httpx.Client")
    def test_token_api_failure_falls_back_to_public_url(self, mock_client_cls: MagicMock) -> None:
        api_client = MagicMock()
        api_resp = MagicMock(status_code=403)
        api_resp.json.return_value = {"message": "forbidden"}
        api_client.get.return_value = api_resp
        api_client.__enter__.return_value = api_client
        api_client.__exit__.return_value = False

        public_client = MagicMock()
        public_resp = MagicMock(status_code=200)
        public_resp.text = "<html><body><h1>Public Body</h1></body></html>"
        public_client.get.return_value = public_resp
        public_client.__enter__.return_value = public_client
        public_client.__exit__.return_value = False

        mock_client_cls.side_effect = [api_client, public_client]

        self.assertEqual(read_notion_page(self._URL), "Public Body")


class TestApprovalHardFail(unittest.IsolatedAsyncioTestCase):
    @patch("routers.approval.refine_with_document")
    @patch("routers.approval.insert_history")
    @patch("routers.approval.read_notion_page")
    @patch("routers.approval.read_workspace_document")
    async def test_google_none_fails(
        self,
        mock_read_doc: MagicMock,
        mock_read_notion: MagicMock,
        mock_insert: MagicMock,
        mock_refine: MagicMock,
    ) -> None:
        from routers.approval import _insert_refined_history_with_token

        mock_read_doc.return_value = None
        pending = {
            "full_text": "https://docs.google.com/document/d/abc123/edit",
        }
        with self.assertRaises(RuntimeError):
            await _insert_refined_history_with_token(pending, "token")
        mock_insert.assert_not_called()

    @patch("routers.approval.refine_with_document")
    @patch("routers.approval.insert_history")
    @patch("routers.approval.read_notion_page")
    @patch("routers.approval.read_workspace_document")
    async def test_google_exception_fails(
        self,
        mock_read_doc: MagicMock,
        mock_read_notion: MagicMock,
        mock_insert: MagicMock,
        mock_refine: MagicMock,
    ) -> None:
        from routers.approval import _insert_refined_history_with_token

        mock_read_doc.side_effect = ValueError("boom")
        pending = {
            "full_text": "https://docs.google.com/document/d/abc123/edit",
        }
        with self.assertRaises(RuntimeError):
            await _insert_refined_history_with_token(pending, "token")
        mock_insert.assert_not_called()

    @patch("routers.approval.refine_with_document")
    @patch("routers.approval.insert_history")
    @patch("routers.approval.read_notion_page")
    @patch("routers.approval.read_workspace_document")
    async def test_notion_exception_fails(
        self,
        mock_read_doc: MagicMock,
        mock_read_notion: MagicMock,
        mock_insert: MagicMock,
        mock_refine: MagicMock,
    ) -> None:
        from routers.approval import _insert_refined_history_with_token

        mock_read_notion.side_effect = RuntimeError("notion fail")
        pending = {
            "full_text": "https://www.notion.so/ws/Page-abc123def4567890abcdef1234567890",
        }
        with self.assertRaises(RuntimeError):
            await _insert_refined_history_with_token(pending, None)
        mock_insert.assert_not_called()

    @patch("routers.approval.refine_with_document")
    @patch("routers.approval.insert_history")
    @patch("routers.approval.invalidate_system_cache")
    @patch("routers.approval.read_notion_page")
    @patch("routers.approval.read_workspace_document")
    async def test_both_docs_merged(
        self,
        mock_read_doc: MagicMock,
        mock_read_notion: MagicMock,
        mock_invalidate: MagicMock,
        mock_insert: MagicMock,
        mock_refine: MagicMock,
    ) -> None:
        from routers.approval import _insert_refined_history_with_token
        from services.gemini_service import RefinedFeedback

        mock_read_doc.return_value = "google body"
        mock_read_notion.return_value = "notion body"
        mock_refine.return_value = RefinedFeedback(
            date="2026-01-01",
            topic="t",
            summary="s",
            scope="전체",
            type="규칙",
            original_quote="q",
            category="크리에이티브",
        )
        mock_insert.return_value = 99

        g_url = "https://docs.google.com/document/d/abc123def4567890abcdef12345678/edit"
        n_url = "https://www.notion.so/ws/Page-abc123def4567890abcdef1234567890"
        pending = {"full_text": f"{g_url}\n{n_url}"}

        await _insert_refined_history_with_token(pending, "token")

        doc_content = mock_refine.call_args[0][1]
        self.assertIn("google body", doc_content)
        self.assertIn("notion body", doc_content)
        self.assertIn("---", doc_content)

    @patch("routers.approval.refine_with_document")
    @patch("routers.approval.insert_history")
    @patch("routers.approval.invalidate_system_cache")
    @patch("routers.approval.read_notion_page")
    @patch("routers.approval.read_workspace_document")
    async def test_no_links_proceeds(
        self,
        mock_read_doc: MagicMock,
        mock_read_notion: MagicMock,
        mock_invalidate: MagicMock,
        mock_insert: MagicMock,
        mock_refine: MagicMock,
    ) -> None:
        from routers.approval import _insert_refined_history_with_token
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

        await _insert_refined_history_with_token({"full_text": "plain text"}, None)

        mock_read_doc.assert_not_called()
        mock_read_notion.assert_not_called()
        self.assertIsNone(mock_refine.call_args[0][1])
        mock_insert.assert_called_once()


if __name__ == "__main__":
    unittest.main()
