"""Tests for ctftime_events and github_repos_by_stars tools."""

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
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    config = AppConfig(llm=LLMConfig())
    state = StateStore(tmp_path)
    loader = SkillLoader(SKILLS_DIR)
    return Tools(config, state, loader)


# ---------------------------------------------------------------------------
# ctftime_events
# ---------------------------------------------------------------------------


SAMPLE_EVENTS = [
    {
        "ctftime_url": "https://ctftime.org/event/100/",
        "title": "Big CTF 2026",
        "format": "Jeopardy",
        "start": "2026-06-15T12:00:00+00:00",
        "finish": "2026-06-16T12:00:00+00:00",
        "restrictions": "Open",
        "weight": 50.0,
        "onsite": False,
        "duration": {"days": 1, "hours": 0},
        "url": "https://bigctf.org/",
        "participants": 200,
    },
    {
        "ctftime_url": "https://ctftime.org/event/200/",
        "title": "Small CTF",
        "format": "Attack-Defense",
        "start": "2026-06-20T12:00:00+00:00",
        "finish": "2026-06-21T12:00:00+00:00",
        "restrictions": "Open",
        "weight": 10.0,
    },
    {
        "ctftime_url": "https://ctftime.org/event/300/",
        "title": "Top Tier",
        "format": "Jeopardy",
        "start": "2026-07-01T12:00:00+00:00",
        "finish": "2026-07-02T12:00:00+00:00",
        "restrictions": "Open",
        "weight": 80.0,
    },
]


def _fake_ctftime_resp(events: list[dict], status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = events
    resp.text = ""
    return resp


def test_ctftime_returns_results(tools):
    with patch("guide_agent.agent.tools.httpx.Client") as mock_cls:
        mc = MagicMock()
        mc.get.return_value = _fake_ctftime_resp(SAMPLE_EVENTS)
        mock_cls.return_value.__enter__.return_value = mc

        r = tools.ctftime_events()
    titles = [x["title"] for x in r["results"]]
    assert "Big CTF 2026" in titles
    assert "Small CTF" in titles
    assert "Top Tier" in titles


def test_ctftime_filters_by_min_weight(tools):
    with patch("guide_agent.agent.tools.httpx.Client") as mock_cls:
        mc = MagicMock()
        mc.get.return_value = _fake_ctftime_resp(SAMPLE_EVENTS)
        mock_cls.return_value.__enter__.return_value = mc

        r = tools.ctftime_events(min_weight=25.0)
    titles = [x["title"] for x in r["results"]]
    assert "Small CTF" not in titles  # weight=10
    assert "Big CTF 2026" in titles  # weight=50
    assert "Top Tier" in titles  # weight=80


def test_ctftime_sorts_by_weight_desc(tools):
    with patch("guide_agent.agent.tools.httpx.Client") as mock_cls:
        mc = MagicMock()
        mc.get.return_value = _fake_ctftime_resp(SAMPLE_EVENTS)
        mock_cls.return_value.__enter__.return_value = mc

        r = tools.ctftime_events()
    titles = [x["title"] for x in r["results"]]
    # Top Tier (80) > Big CTF (50) > Small CTF (10)
    assert titles == ["Top Tier", "Big CTF 2026", "Small CTF"]


def test_ctftime_respects_limit(tools):
    with patch("guide_agent.agent.tools.httpx.Client") as mock_cls:
        mc = MagicMock()
        mc.get.return_value = _fake_ctftime_resp(SAMPLE_EVENTS)
        mock_cls.return_value.__enter__.return_value = mc

        r = tools.ctftime_events(limit=2)
    assert r["returned_count"] == 2


def test_ctftime_handles_http_error(tools):
    with patch("guide_agent.agent.tools.httpx.Client") as mock_cls:
        mc = MagicMock()
        mc.get.return_value = _fake_ctftime_resp([], status=500)
        mc.get.return_value.text = "boom"
        mock_cls.return_value.__enter__.return_value = mc

        r = tools.ctftime_events()
    assert "error" in r
    assert "500" in r["error"]


def test_ctftime_handles_network_failure(tools):
    with patch("guide_agent.agent.tools.httpx.Client") as mock_cls:
        mc = MagicMock()
        mc.get.side_effect = httpx.ConnectError("nope")
        mock_cls.return_value.__enter__.return_value = mc

        r = tools.ctftime_events()
    assert "error" in r


def test_ctftime_dispatchable(tools):
    with patch("guide_agent.agent.tools.httpx.Client") as mock_cls:
        mc = MagicMock()
        mc.get.return_value = _fake_ctftime_resp(SAMPLE_EVENTS)
        mock_cls.return_value.__enter__.return_value = mc

        r = tools.dispatch("ctftime_events", {"limit": 5})
    assert "results" in r


# ---------------------------------------------------------------------------
# github_repos_by_stars
# ---------------------------------------------------------------------------


SAMPLE_REPOS = {
    "items": [
        {
            "html_url": "https://github.com/expressjs/express",
            "full_name": "expressjs/express",
            "description": "Fast, unopinionated Node.js framework",
            "stargazers_count": 67000,
            "forks_count": 12000,
            "language": "JavaScript",
            "topics": ["nodejs", "framework", "web"],
            "pushed_at": "2026-05-01T00:00:00Z",
            "license": {"spdx_id": "MIT"},
            "archived": False,
        },
        {
            "html_url": "https://github.com/vercel/next.js",
            "full_name": "vercel/next.js",
            "description": "React framework",
            "stargazers_count": 133000,
            "forks_count": 28000,
            "language": "JavaScript",
            "topics": ["nextjs", "react"],
            "pushed_at": "2026-06-01T00:00:00Z",
            "license": {"spdx_id": "MIT"},
            "archived": False,
        },
    ],
    "total_count": 2,
}


def _fake_gh_resp(body, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body
    resp.text = ""
    return resp


def test_github_stars_rejects_empty_query(tools):
    r = tools.github_repos_by_stars(query="")
    assert "error" in r


def test_github_stars_returns_results(tools):
    with patch("guide_agent.agent.tools.httpx.Client") as mock_cls:
        mc = MagicMock()
        mc.get.return_value = _fake_gh_resp(SAMPLE_REPOS)
        mock_cls.return_value.__enter__.return_value = mc

        r = tools.github_repos_by_stars(query="language:javascript")
    names = [x["full_name"] for x in r["results"]]
    assert "expressjs/express" in names
    assert "vercel/next.js" in names


def test_github_stars_appends_min_stars_filter(tools):
    with patch("guide_agent.agent.tools.httpx.Client") as mock_cls:
        mc = MagicMock()
        mc.get.return_value = _fake_gh_resp(SAMPLE_REPOS)
        mock_cls.return_value.__enter__.return_value = mc

        tools.github_repos_by_stars(query="topic:framework", min_stars=10000)

    sent_q = mc.get.call_args.kwargs["params"]["q"]
    assert "stars:>10000" in sent_q


def test_github_stars_skips_appending_if_already_present(tools):
    with patch("guide_agent.agent.tools.httpx.Client") as mock_cls:
        mc = MagicMock()
        mc.get.return_value = _fake_gh_resp(SAMPLE_REPOS)
        mock_cls.return_value.__enter__.return_value = mc

        tools.github_repos_by_stars(
            query="topic:web stars:>50000", min_stars=10000,
        )

    sent_q = mc.get.call_args.kwargs["params"]["q"]
    assert sent_q.count("stars:") == 1
    assert "stars:>50000" in sent_q


def test_github_stars_sort_params(tools):
    with patch("guide_agent.agent.tools.httpx.Client") as mock_cls:
        mc = MagicMock()
        mc.get.return_value = _fake_gh_resp(SAMPLE_REPOS)
        mock_cls.return_value.__enter__.return_value = mc

        tools.github_repos_by_stars(query="topic:framework")

    params = mc.get.call_args.kwargs["params"]
    assert params["sort"] == "stars"
    assert params["order"] == "desc"


def test_github_stars_handles_403(tools):
    with patch("guide_agent.agent.tools.httpx.Client") as mock_cls:
        mc = MagicMock()
        mc.get.return_value = _fake_gh_resp({}, status=403)
        mc.get.return_value.text = "rate limited"
        mock_cls.return_value.__enter__.return_value = mc

        r = tools.github_repos_by_stars(query="javascript")
    assert "error" in r
    assert "GITHUB_TOKEN" in r["error"]


def test_github_stars_uses_token_when_present(tools, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    with patch("guide_agent.agent.tools.httpx.Client") as mock_cls:
        mc = MagicMock()
        mc.get.return_value = _fake_gh_resp(SAMPLE_REPOS)
        mock_cls.return_value.__enter__.return_value = mc

        tools.github_repos_by_stars(query="javascript")

    headers = mock_cls.call_args.kwargs["headers"]
    assert headers.get("Authorization") == "Bearer ghp_test"


def test_github_stars_omits_token_when_absent(tools):
    with patch("guide_agent.agent.tools.httpx.Client") as mock_cls:
        mc = MagicMock()
        mc.get.return_value = _fake_gh_resp(SAMPLE_REPOS)
        mock_cls.return_value.__enter__.return_value = mc

        tools.github_repos_by_stars(query="javascript")

    headers = mock_cls.call_args.kwargs["headers"]
    assert "Authorization" not in headers


def test_github_stars_dispatchable(tools):
    with patch("guide_agent.agent.tools.httpx.Client") as mock_cls:
        mc = MagicMock()
        mc.get.return_value = _fake_gh_resp(SAMPLE_REPOS)
        mock_cls.return_value.__enter__.return_value = mc

        r = tools.dispatch("github_repos_by_stars", {"query": "javascript"})
    assert "results" in r
