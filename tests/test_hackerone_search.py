"""Tests for hackerone_hacktivity_search — Lucene builder + main behavior."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from guide_agent.agent.tools import (
    _SEVERITY_RANK,
    Tools,
    _build_hacktivity_lucene,
)
from guide_agent.config import AppConfig, LLMConfig
from guide_agent.skills.loader import SkillLoader
from guide_agent.state.store import StateStore

SKILLS_DIR = "src/guide_agent/skills"


# ---------------------------------------------------------------------------
# _build_hacktivity_lucene
# ---------------------------------------------------------------------------


def test_lucene_basic_high():
    q = _build_hacktivity_lucene("xss", "high", 0)
    assert q == "(xss) AND (severity_rating:high OR severity_rating:critical)"


def test_lucene_critical_only():
    q = _build_hacktivity_lucene("postmessage", "critical", 0)
    assert q == "(postmessage) AND (severity_rating:critical)"


def test_lucene_medium_floor_includes_all_above():
    q = _build_hacktivity_lucene("ssrf", "medium", 0)
    assert "severity_rating:medium" in q
    assert "severity_rating:high" in q
    assert "severity_rating:critical" in q
    assert "severity_rating:low" not in q
    assert "severity_rating:none" not in q


def test_lucene_with_bounty_floor():
    q = _build_hacktivity_lucene("xss", "high", 500)
    assert q.endswith("AND total_awarded_amount:[500 TO *]")


def test_lucene_zero_bounty_omits_range():
    q = _build_hacktivity_lucene("xss", "high", 0)
    assert "total_awarded_amount" not in q


def test_lucene_multi_word_query_wrapped():
    q = _build_hacktivity_lucene("prototype pollution", "high", 0)
    assert q.startswith("(prototype pollution)")


def test_severity_rank_complete():
    assert set(_SEVERITY_RANK.keys()) == {"none", "low", "medium", "high", "critical"}
    assert _SEVERITY_RANK["critical"] > _SEVERITY_RANK["high"] > _SEVERITY_RANK["low"]


# ---------------------------------------------------------------------------
# hackerone_hacktivity_search end-to-end (mocked httpx)
# ---------------------------------------------------------------------------


@pytest.fixture
def tools(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    config = AppConfig(llm=LLMConfig())
    state = StateStore(tmp_path)
    loader = SkillLoader(SKILLS_DIR)
    return Tools(config, state, loader)


def _fake_gql_response(
    nodes: list[dict],
    total_count: int | None = None,
    status_code: int = 200,
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {
        "data": {
            "search": {
                "total_count": total_count if total_count is not None else len(nodes),
                "nodes": nodes,
            }
        }
    }
    return resp


def test_search_rejects_empty_bug_class(tools):
    result = tools.hackerone_hacktivity_search(bug_class="   ")
    assert "error" in result


def test_search_rejects_bad_severity(tools):
    result = tools.hackerone_hacktivity_search(bug_class="xss", min_severity="silly")
    assert "error" in result
    assert "min_severity" in result["error"]


def test_search_rejects_bad_min_bounty(tools):
    result = tools.hackerone_hacktivity_search(
        bug_class="xss", min_bounty="banana",
    )
    assert "error" in result


def test_search_sorts_by_severity_then_bounty(tools):
    """Critical $0 should come before High $99999 — severity wins first."""
    fake_nodes = [
        {"_id": "1", "severity_rating": "High", "total_awarded_amount": 99999,
         "cwe": "XSS", "votes": 1, "submitted_at": "x", "currency": "USD"},
        {"_id": "2", "severity_rating": "Critical", "total_awarded_amount": 0,
         "cwe": "XSS", "votes": 1, "submitted_at": "x", "currency": "USD"},
        {"_id": "3", "severity_rating": "Critical", "total_awarded_amount": 5000,
         "cwe": "XSS", "votes": 1, "submitted_at": "x", "currency": "USD"},
    ]
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.return_value = _fake_gql_response(fake_nodes)
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = tools.hackerone_hacktivity_search(
            bug_class="xss", min_severity="high", limit=10,
        )

    ids = [r["report_id"] for r in result["results"]]
    # Critical $5000 > Critical $0 > High $99999
    assert ids == ["3", "2", "1"]


def test_search_returns_constructed_urls(tools):
    fake_nodes = [
        {"_id": "1234567", "severity_rating": "High", "total_awarded_amount": 1000,
         "cwe": "XSS", "votes": 5, "submitted_at": "x", "currency": "USD"},
    ]
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.return_value = _fake_gql_response(fake_nodes)
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = tools.hackerone_hacktivity_search(bug_class="xss", limit=5)

    assert result["results"][0]["url"] == "https://hackerone.com/reports/1234567"


def test_search_respects_limit(tools):
    fake_nodes = [
        {"_id": str(i), "severity_rating": "High", "total_awarded_amount": i,
         "cwe": "XSS", "votes": 1, "submitted_at": "x", "currency": "USD"}
        for i in range(20)
    ]
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.return_value = _fake_gql_response(
            fake_nodes, total_count=20,
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = tools.hackerone_hacktivity_search(
            bug_class="xss", limit=5,
        )
    assert len(result["results"]) == 5
    assert result["returned_count"] == 5


def test_search_handles_graphql_errors(tools):
    bad_resp = MagicMock()
    bad_resp.status_code = 200
    bad_resp.json.return_value = {
        "errors": [{"message": "field not defined"}],
        "data": None,
    }
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.return_value = bad_resp
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = tools.hackerone_hacktivity_search(bug_class="xss")
    assert "error" in result
    assert "graphql_errors" in result


def test_search_handles_http_error(tools):
    bad_resp = MagicMock()
    bad_resp.status_code = 500
    bad_resp.text = "server explosion"
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.return_value = bad_resp
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = tools.hackerone_hacktivity_search(bug_class="xss")
    assert "error" in result
    assert "500" in result["error"]


def test_search_handles_network_failure(tools):
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.ConnectError("nope")
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = tools.hackerone_hacktivity_search(bug_class="xss")
    assert "error" in result


def test_search_dispatchable_via_tools_dispatch(tools):
    fake_nodes = [
        {"_id": "1", "severity_rating": "Critical", "total_awarded_amount": 1000,
         "cwe": "XSS", "votes": 1, "submitted_at": "x", "currency": "USD"},
    ]
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.return_value = _fake_gql_response(fake_nodes)
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = tools.dispatch("hackerone_hacktivity_search", {
            "bug_class": "xss",
            "min_severity": "critical",
            "min_bounty": 500,
            "limit": 5,
        })
    assert "results" in result
    assert result["bug_class"] == "xss"


def test_search_exposes_lucene_query_for_debugging(tools):
    fake_nodes = []
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.return_value = _fake_gql_response(
            fake_nodes, total_count=0,
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = tools.hackerone_hacktivity_search(
            bug_class="xss", min_severity="high", min_bounty=1000,
        )
    assert "lucene_query" in result
    assert "severity_rating:high" in result["lucene_query"]
    assert "[1000 TO *]" in result["lucene_query"]


def test_search_normalizes_severity_lowercase(tools):
    fake_nodes = [
        {"_id": "1", "severity_rating": "High", "total_awarded_amount": 100,
         "cwe": "XSS", "votes": 1, "submitted_at": "x", "currency": "USD"},
    ]
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.return_value = _fake_gql_response(fake_nodes)
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = tools.hackerone_hacktivity_search(
            bug_class="xss", min_severity="HIGH",
        )
    assert "error" not in result


def test_search_result_fields_complete(tools):
    fake_nodes = [
        {"_id": "999", "severity_rating": "Critical",
         "total_awarded_amount": 5000, "cwe": "XSS Stored",
         "votes": 42, "submitted_at": "2025-01-01", "currency": "USD",
         "industry": "Tech",
         "report": {"title": "Critical XSS in checkout"},
         "team": {"handle": "shopify"}},
    ]
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.return_value = _fake_gql_response(fake_nodes)
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = tools.hackerone_hacktivity_search(bug_class="xss", limit=1)
    r = result["results"][0]
    assert r["url"] == "https://hackerone.com/reports/999"
    assert r["severity"] == "Critical"
    assert r["bounty"] == 5000
    assert r["cwe"] == "XSS Stored"
    assert r["votes"] == 42
    assert r["industry"] == "Tech"
    assert r["currency"] == "USD"
    assert r["title"] == "Critical XSS in checkout"
    assert r["team_handle"] == "shopify"


def test_search_handles_missing_title_and_team(tools):
    """Older reports may have null report/team — must not crash."""
    fake_nodes = [
        {"_id": "1", "severity_rating": "High", "total_awarded_amount": 100,
         "cwe": "XSS", "votes": 1, "submitted_at": "x", "currency": "USD",
         "report": None, "team": None},
    ]
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.return_value = _fake_gql_response(fake_nodes)
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = tools.hackerone_hacktivity_search(bug_class="xss", limit=1)
    r = result["results"][0]
    assert r["title"] is None
    assert r["team_handle"] is None


def test_search_limit_capped_at_200(tools):
    fake_nodes = [
        {"_id": str(i), "severity_rating": "High", "total_awarded_amount": 100,
         "cwe": "XSS", "votes": 1, "submitted_at": "x", "currency": "USD"}
        for i in range(500)
    ]
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.return_value = _fake_gql_response(
            fake_nodes, total_count=500,
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = tools.hackerone_hacktivity_search(
            bug_class="xss", limit=999,
        )
    assert len(result["results"]) == 200


def test_search_exclude_report_ids(tools):
    fake_nodes = [
        {"_id": "100", "severity_rating": "High", "total_awarded_amount": 1000,
         "cwe": "XSS", "votes": 1, "submitted_at": "x", "currency": "USD"},
        {"_id": "200", "severity_rating": "High", "total_awarded_amount": 2000,
         "cwe": "XSS", "votes": 1, "submitted_at": "x", "currency": "USD"},
        {"_id": "300", "severity_rating": "High", "total_awarded_amount": 3000,
         "cwe": "XSS", "votes": 1, "submitted_at": "x", "currency": "USD"},
    ]
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.return_value = _fake_gql_response(fake_nodes)
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = tools.hackerone_hacktivity_search(
            bug_class="xss",
            exclude_report_ids=["100", "300"],
            limit=10,
        )
    ids = [r["report_id"] for r in result["results"]]
    assert ids == ["200"]
    assert result["excluded_count"] == 2


def test_search_exclude_ignores_blank_entries(tools):
    fake_nodes = [
        {"_id": "1", "severity_rating": "High", "total_awarded_amount": 100,
         "cwe": "XSS", "votes": 1, "submitted_at": "x", "currency": "USD"},
    ]
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.return_value = _fake_gql_response(fake_nodes)
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = tools.hackerone_hacktivity_search(
            bug_class="xss",
            exclude_report_ids=["", "   ", None],  # type: ignore[list-item]
        )
    assert result["excluded_count"] == 0
    assert len(result["results"]) == 1


def test_search_exclude_defaults_to_empty(tools):
    fake_nodes = [
        {"_id": "1", "severity_rating": "High", "total_awarded_amount": 100,
         "cwe": "XSS", "votes": 1, "submitted_at": "x", "currency": "USD"},
    ]
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.return_value = _fake_gql_response(fake_nodes)
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = tools.hackerone_hacktivity_search(bug_class="xss")
    assert result["excluded_count"] == 0
