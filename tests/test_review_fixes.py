import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


class TestSlackThreadPagination(unittest.TestCase):
    @patch("services.slack_service._client")
    def test_paginates_and_excludes_parent(self, mock_client_fn: MagicMock) -> None:
        from services.slack_service import fetch_thread_replies

        client = MagicMock()
        client.conversations_replies.side_effect = [
            {
                "messages": [{"ts": "1.0"}, {"ts": "1.1"}],
                "has_more": True,
                "response_metadata": {"next_cursor": "CUR1"},
            },
            {"messages": [{"ts": "1.2"}], "has_more": False},
        ]
        mock_client_fn.return_value = client

        out = fetch_thread_replies("CHAN", "1.0")

        # 부모(ts == thread_ts) 제외, 모든 페이지 수집
        self.assertEqual([m["ts"] for m in out], ["1.1", "1.2"])
        self.assertEqual(client.conversations_replies.call_count, 2)
        _, kwargs = client.conversations_replies.call_args_list[1]
        self.assertEqual(kwargs.get("cursor"), "CUR1")


class TestGdriveOAuthState(unittest.TestCase):
    @patch.dict(os.environ, {"GOOGLE_CLIENT_SECRET": "gsec"})
    def test_state_verify(self) -> None:
        import routers.gdrive as g

        nonce = "nonce-abc"
        cookie = f"{nonce}.{g._sign_oauth_nonce(nonce)}"
        self.assertTrue(g._verify_oauth_state_cookie(cookie, nonce))
        self.assertFalse(g._verify_oauth_state_cookie(cookie, "other"))
        self.assertFalse(g._verify_oauth_state_cookie(None, nonce))
        self.assertFalse(g._verify_oauth_state_cookie("nonce-abc.deadbeef", nonce))
        self.assertFalse(g._verify_oauth_state_cookie(cookie, ""))


class TestInspectBase64Limit(unittest.TestCase):
    def test_oversized_b64_rejected(self) -> None:
        from fastapi import HTTPException

        from models.schemas import InspectRequest
        from routers.inspect import _MAX_IMAGE_B64_LEN, _build_contents

        big = "A" * (_MAX_IMAGE_B64_LEN + 1)
        req = InspectRequest(
            message="m", image_base64=big, image_media_type="image/png", mode="소재검수"
        )
        with self.assertRaises(HTTPException) as ctx:
            _build_contents(req)
        self.assertEqual(ctx.exception.status_code, 413)

    def test_small_b64_ok(self) -> None:
        import base64 as b64mod

        from models.schemas import InspectRequest
        from routers.inspect import _build_contents

        data = b64mod.b64encode(b"hello world").decode()
        req = InspectRequest(
            message="m", image_base64=data, image_media_type="image/png", mode="소재검수"
        )
        out = _build_contents(req)
        self.assertIsInstance(out, list)
        self.assertEqual(out[-1], "m")


class TestSlackPipeLinkPreservesUrl(unittest.TestCase):
    def test_pipe_link_keeps_url_for_extraction(self) -> None:
        from services.slack_service import (
            clean_slack_markup,
            extract_document_links,
            extract_notion_links,
        )

        raw = (
            "<https://www.notion.so/Brand-OS-365b901b86d780409783d813f274f06b|올더뮤 Brand OS> "
            "<https://docs.google.com/document/d/abc123XYZ/edit|기획서>"
        )
        cleaned = clean_slack_markup(raw)
        self.assertIn("notion.so/Brand-OS", cleaned)
        self.assertEqual(len(extract_notion_links(cleaned)), 1)
        self.assertEqual(len(extract_document_links(cleaned)), 1)


class TestApproveConcurrency(unittest.IsolatedAsyncioTestCase):
    @patch("routers.approval.claim_pending_status", return_value=False)
    @patch("routers.approval._ensure_tokens_for_docs", new_callable=AsyncMock)
    @patch("routers.approval.get_pending_approval_by_id")
    async def test_approve_returns_409_when_claim_lost(
        self, mock_get: MagicMock, mock_ensure: AsyncMock, mock_claim: MagicMock
    ) -> None:
        from fastapi import HTTPException

        from routers.approval import approve

        mock_get.return_value = {"id": 5, "status": "대기중"}
        mock_ensure.return_value = (None, None)

        with self.assertRaises(HTTPException) as ctx:
            await approve(5, MagicMock(), MagicMock())
        self.assertEqual(ctx.exception.status_code, 409)
        mock_claim.assert_called_once_with(5, "대기중", "처리중")


if __name__ == "__main__":
    unittest.main()
