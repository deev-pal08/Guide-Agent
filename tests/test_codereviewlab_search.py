"""Tests for codereviewlab_search — Code Review Lab API wrapping."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

import guide_agent.agent.tools as tools_mod
from guide_agent.agent.tools import Tools
from guide_agent.config import AppConfig, LLMConfig
from guide_agent.skills.loader import SkillLoader
from guide_agent.state.store import StateStore

SKILLS_DIR = "src/guide_agent/skills"


SAMPLE_CHALLENGES = [
    {"id": "c1", "title": "Stored XSS in profile",
     "vulnType": "XSS (Cross-Site Scripting)", "language": "PHP",
     "difficulty": "EASY", "points": 100, "platform": "Web",
     "description": "User input rendered without escaping."},
    {"id": "c2", "title": "Reflected XSS in search",
     "vulnType": "XSS (Cross-Site Scripting)", "language": "JavaScript / TypeScript",
     "difficulty": "MEDIUM", "points": 200, "platform": "Web",
     "description": "Search reflects raw query."},
    {"id": "c3", "title": "SSRF via avatar URL",
     "vulnType": "SSRF (Server-Side Request Forgery)", "language": "Go",
     "difficulty": "HARD", "points": 300, "platform": "Web",
     "description": "Profile loads remote avatar."},
    {"id": "c4", "title": "Unauthenticated RCE",
     "vulnType": "RCE (Remote Code Execution)", "language": "Python",
     "difficulty": "HARD", "points": 400, "platform": "Web",
     "description": "eval() over user input."},
    {"id": "c5", "title": "JWT none algorithm",
     "vulnType": "JWT (JSON Web Tokens)", "language": "Java",
     "difficulty": "MEDIUM", "points": 200, "platform": "Web",
     "description": "JWT accepts alg:none."},
]


@pytest.fixture
def tools(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    config = AppConfig(llm=LLMConfig())
    state = StateStore(tmp_path)
    loader = SkillLoader(SKILLS_DIR)
    tools_mod._codereviewlab_cache = None
    return Tools(config, state, loader)


@pytest.fixture
def patched_loader():
    with patch.object(tools_mod, "_load_codereviewlab_challenges",
                      return_value=SAMPLE_CHALLENGES) as m:
        yield m


def test_search_rejects_empty_bug_class(tools):
    r = tools.codereviewlab_search(bug_class="   ")
    assert "error" in r


def test_search_filters_by_vuln_type(tools, patched_loader):
    r = tools.codereviewlab_search(bug_class="xss")
    titles = [x["title"] for x in r["results"]]
    assert "Stored XSS in profile" in titles
    assert "Reflected XSS in search" in titles
    assert "SSRF via avatar URL" not in titles
    assert r["total_count"] == 2


def test_search_supports_pipe_synonyms(tools, patched_loader):
    r = tools.codereviewlab_search(bug_class="xss|ssrf")
    titles = [x["title"] for x in r["results"]]
    assert "Stored XSS in profile" in titles
    assert "SSRF via avatar URL" in titles
    assert "Unauthenticated RCE" not in titles


def test_search_filters_by_language(tools, patched_loader):
    r = tools.codereviewlab_search(bug_class="xss", language="PHP")
    titles = [x["title"] for x in r["results"]]
    assert titles == ["Stored XSS in profile"]


def test_search_filters_by_difficulty(tools, patched_loader):
    r = tools.codereviewlab_search(bug_class="xss", difficulty="EASY")
    titles = [x["title"] for x in r["results"]]
    assert titles == ["Stored XSS in profile"]


def test_search_constructs_challenge_url(tools, patched_loader):
    r = tools.codereviewlab_search(bug_class="ssrf")
    assert r["results"][0]["url"] == "https://www.codereviewlab.com/challenges/c3"


def test_search_respects_limit(tools):
    many = [
        {"id": f"x{i}", "title": f"XSS {i}",
         "vulnType": "XSS (Cross-Site Scripting)", "language": "PHP",
         "difficulty": "EASY", "points": 100, "platform": "Web",
         "description": ""}
        for i in range(30)
    ]
    with patch.object(tools_mod, "_load_codereviewlab_challenges",
                      return_value=many):
        r = tools.codereviewlab_search(bug_class="xss", limit=5)
    assert r["returned_count"] == 5
    assert r["total_count"] == 30


def test_search_limit_capped_at_100(tools):
    many = [
        {"id": f"x{i}", "title": f"XSS {i}",
         "vulnType": "XSS (Cross-Site Scripting)", "language": "PHP",
         "difficulty": "EASY", "points": 100, "platform": "Web",
         "description": ""}
        for i in range(300)
    ]
    with patch.object(tools_mod, "_load_codereviewlab_challenges",
                      return_value=many):
        r = tools.codereviewlab_search(bug_class="xss", limit=9999)
    assert r["returned_count"] == 100


def test_search_handles_loader_failure(tools):
    with patch.object(tools_mod, "_load_codereviewlab_challenges",
                      side_effect=httpx.ConnectError("nope")):
        r = tools.codereviewlab_search(bug_class="xss")
    assert "error" in r


def test_search_dispatchable(tools, patched_loader):
    r = tools.dispatch("codereviewlab_search", {"bug_class": "xss"})
    assert "results" in r


def test_loader_caches_response(tools):
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {"challenges": SAMPLE_CHALLENGES}

    call_count = {"n": 0}

    def fake_get(*a, **kw):
        call_count["n"] += 1
        return fake_resp

    fake_client = MagicMock()
    fake_client.get = fake_get
    with patch.object(tools_mod.httpx, "Client") as mock_cls:
        mock_cls.return_value.__enter__.return_value = fake_client
        tools.codereviewlab_search(bug_class="xss")
        tools.codereviewlab_search(bug_class="ssrf")
    assert call_count["n"] == 1
