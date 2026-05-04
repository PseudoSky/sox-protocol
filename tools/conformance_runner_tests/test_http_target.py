# SPDX-License-Identifier: Apache-2.0
"""Tests for HttpTarget: POST shape, error handling, start/stop."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from conformance_runner import HttpTarget, _op_to_tool


class TestHttpTargetLifecycle:
    """Lifecycle tests for HttpTarget."""

    def test_start_initialises_httpx_client(self) -> None:
        try:
            import httpx  # noqa: F401
        except ImportError:
            pytest.skip("httpx not installed")
        t = HttpTarget("http://localhost:19999")
        t.start("agent-x")
        assert t._session is not None
        t.stop()

    def test_stop_clears_session(self) -> None:
        try:
            import httpx  # noqa: F401
        except ImportError:
            pytest.skip("httpx not installed")
        t = HttpTarget("http://localhost:19999")
        t.start("agent-x")
        t.stop()
        assert t._session is None

    def test_stop_twice_is_safe(self) -> None:
        try:
            import httpx  # noqa: F401
        except ImportError:
            pytest.skip("httpx not installed")
        t = HttpTarget("http://localhost:19999")
        t.start("agent-x")
        t.stop()
        t.stop()

    def test_start_without_httpx_raises_runtime_error(self) -> None:
        t = HttpTarget("http://localhost:19999")
        import builtins
        real_import = builtins.__import__

        def mock_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "httpx":
                raise ImportError("No module named 'httpx'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            with pytest.raises(RuntimeError, match="httpx is required"):
                t.start("agent-x")


class TestHttpTargetCallTool:
    """Tests for HttpTarget.call_tool() with mocked httpx."""

    @pytest.fixture()
    def mock_session(self) -> MagicMock:
        session = MagicMock()
        mock_resp = MagicMock()
        # status_code MUST be a real int — HttpTarget.call_tool branches on
        # `resp.status_code >= 400` for the sox-error envelope path. A bare
        # MagicMock can't be compared with `>=` and raises TypeError.
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "drained_at": 1234567890.0,
            "messages": [],
        }
        mock_resp.raise_for_status.return_value = None
        session.post.return_value = mock_resp
        return session

    def test_call_tool_posts_to_correct_url(self, mock_session: MagicMock) -> None:
        t = HttpTarget("http://localhost:9876")
        t._session = mock_session
        t.call_tool("agent-a", "recv", {})
        mock_session.post.assert_called_once()
        call_args = mock_session.post.call_args
        assert "/v1/ops/recv" in call_args[0][0]

    def test_call_tool_sets_agent_id_header(self, mock_session: MagicMock) -> None:
        t = HttpTarget("http://localhost:9876")
        t._session = mock_session
        t.call_tool("my-agent-id", "recv", {})
        call_kwargs = mock_session.post.call_args[1]
        assert call_kwargs["headers"]["X-SOX-Agent-ID"] == "my-agent-id"

    def test_call_tool_sends_args_as_json(self, mock_session: MagicMock) -> None:
        t = HttpTarget("http://localhost:9876")
        t._session = mock_session
        args = {"channel": "test:ch", "body": {"x": 1}}
        t.call_tool("agent-a", "send", args)
        call_kwargs = mock_session.post.call_args[1]
        assert call_kwargs["json"] == args

    def test_call_tool_returns_parsed_json(self, mock_session: MagicMock) -> None:
        t = HttpTarget("http://localhost:9876")
        t._session = mock_session
        result = t.call_tool("agent-a", "recv", {})
        assert result == {"drained_at": 1234567890.0, "messages": []}

    def test_call_tool_on_http_error_returns_rpc_error(self, mock_session: MagicMock) -> None:
        mock_session.post.side_effect = Exception("Connection refused")
        t = HttpTarget("http://localhost:9876")
        t._session = mock_session
        result = t.call_tool("agent-a", "recv", {})
        assert "_rpc_error" in result
        assert "Connection refused" in result["_rpc_error"]["message"]

    def test_call_tool_sets_content_type_header(self, mock_session: MagicMock) -> None:
        t = HttpTarget("http://localhost:9876")
        t._session = mock_session
        t.call_tool("agent-a", "send", {"channel": "test", "body": {}})
        headers = mock_session.post.call_args[1]["headers"]
        assert headers["Content-Type"] == "application/json"

    def test_base_url_used_for_all_operations(self, mock_session: MagicMock) -> None:
        t = HttpTarget("http://myhost:1234")
        t._session = mock_session
        t.call_tool("agent-a", "subscribe", {"pattern": "test:*"})
        url = mock_session.post.call_args[0][0]
        assert url.startswith("http://myhost:1234")
