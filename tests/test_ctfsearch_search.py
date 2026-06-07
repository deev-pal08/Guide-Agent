"""Tests for ctfsearch_search — Typesense API wrapping."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from guide_agent.agent.tools import Tools
from guide_agent.config import AppConfig, LLMConfig
from guide_agent.skills.loader import SkillLoader
from guide_agent.state.store import StateStore

SKILLS_DIR = "src/guide_agent/skills"


@pytest.fixture
def tools(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    config = AppConfig(llm=LLMConfig())
    state = StateStore(tmp_path)
    loader = SkillLoader(SKILLS_DIR)
    return Tools(config, state, loader)


def _fake_typesense_response(
    hits: list[dict],
    found: int | None = None,
    status_code: int = 200,
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {
        "found": found if found is not None else len(hits),
        "hits": [{"document": d} for d in hits],
    }
    return resp


def test_search_rejects_empty_bug_class(tools):
    result = tools.ctfsearch_search(bug_class="   ")
    assert "error" in result


def test_search_returns_results(tools):
    hits = [
        {"title": "XSS Walkthrough", "url": "https://example.com/xss",
         "category": "Web", "date": "2025-01-01", "id": "1"},
        {"title": "DOM XSS", "url": "https://example.com/dom",
         "category": "Web", "date": "2024-12-15", "id": "2"},
    ]
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get.return_value = _fake_typesense_response(hits, found=42)
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = tools.ctfsearch_search(bug_class="xss", limit=10)

    assert result["bug_class"] == "xss"
    assert result["total_count"] == 42
    assert result["returned_count"] == 2
    titles = [r["title"] for r in result["results"]]
    assert "XSS Walkthrough" in titles
    assert "DOM XSS" in titles


def test_search_sends_api_key_header(tools):
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get.return_value = _fake_typesense_response([])
        mock_client_cls.return_value.__enter__.return_value = mock_client

        tools.ctfsearch_search(bug_class="xss")

    headers = mock_client.get.call_args.kwargs.get("headers", {})
    assert "X-TYPESENSE-API-KEY" in headers
    assert headers["X-TYPESENSE-API-KEY"]  # non-empty


def test_search_passes_query_params(tools):
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get.return_value = _fake_typesense_response([])
        mock_client_cls.return_value.__enter__.return_value = mock_client

        tools.ctfsearch_search(bug_class="postmessage", limit=20)

    params = mock_client.get.call_args.kwargs.get("params", {})
    assert params["q"] == "postmessage"
    assert "title" in params["query_by"]
    assert "content" in params["query_by"]
    assert params["sort_by"].startswith("date:")
    assert params["per_page"] == "20"


def test_search_respects_limit(tools):
    hits = [
        {"title": f"Writeup {i}", "url": f"https://e.com/{i}",
         "category": "Web", "date": "2024-01-01", "id": str(i)}
        for i in range(5)
    ]
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get.return_value = _fake_typesense_response(hits, found=100)
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = tools.ctfsearch_search(bug_class="xss", limit=5)

    assert result["returned_count"] == 5


def test_search_limit_capped_at_100(tools):
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get.return_value = _fake_typesense_response([])
        mock_client_cls.return_value.__enter__.return_value = mock_client

        tools.ctfsearch_search(bug_class="xss", limit=99999)

    params = mock_client.get.call_args.kwargs.get("params", {})
    assert params["per_page"] == "100"


def test_search_handles_http_error(tools):
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        bad = MagicMock()
        bad.status_code = 500
        bad.text = "boom"
        mock_client = MagicMock()
        mock_client.get.return_value = bad
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = tools.ctfsearch_search(bug_class="xss")
    assert "error" in result
    assert "500" in result["error"]


def test_search_handles_network_failure(tools):
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.ConnectError("nope")
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = tools.ctfsearch_search(bug_class="xss")
    assert "error" in result


def test_search_dispatchable(tools):
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get.return_value = _fake_typesense_response([])
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = tools.dispatch("ctfsearch_search", {
            "bug_class": "xss",
            "limit": 5,
        })
    assert "results" in result


def test_search_result_field_shape(tools):
    hits = [
        {"title": "T", "url": "https://e.com/x", "category": "Web",
         "date": "2024-01-01", "id": "99"},
    ]
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get.return_value = _fake_typesense_response(hits)
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = tools.ctfsearch_search(bug_class="xss", limit=1)
    r = result["results"][0]
    assert set(r.keys()) == {"url", "title", "category", "date", "id"}
