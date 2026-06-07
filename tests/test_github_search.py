"""Tests for the github_repo_search tool — helpers + main behavior."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from guide_agent.agent.tools import (
    Tools,
    _normalise_for_match,
    _parse_github_repo,
    _score_repo_path,
)
from guide_agent.config import AppConfig, LLMConfig
from guide_agent.skills.loader import SkillLoader
from guide_agent.state.store import StateStore

SKILLS_DIR = "src/guide_agent/skills"


# ---------------------------------------------------------------------------
# _parse_github_repo
# ---------------------------------------------------------------------------


def test_parse_simple_repo_url():
    assert _parse_github_repo("https://github.com/owner/repo") == ("owner", "repo")


def test_parse_trailing_slash():
    assert _parse_github_repo("https://github.com/owner/repo/") == ("owner", "repo")


def test_parse_strips_dot_git_suffix():
    assert _parse_github_repo("https://github.com/owner/repo.git") == ("owner", "repo")


def test_parse_tree_branch_url():
    assert _parse_github_repo(
        "https://github.com/owner/repo/tree/master"
    ) == ("owner", "repo")


def test_parse_tree_subdir_url():
    assert _parse_github_repo(
        "https://github.com/owner/repo/tree/master/XSS%20Injection"
    ) == ("owner", "repo")


def test_parse_http_not_https():
    assert _parse_github_repo("http://github.com/owner/repo") == ("owner", "repo")


def test_parse_handles_caps():
    assert _parse_github_repo("https://GitHub.com/owner/repo") == ("owner", "repo")


def test_parse_rejects_non_github():
    assert _parse_github_repo("https://gitlab.com/owner/repo") == ("", "")


def test_parse_rejects_garbage():
    assert _parse_github_repo("") == ("", "")
    assert _parse_github_repo("not-a-url") == ("", "")
    assert _parse_github_repo("https://example.com") == ("", "")


# ---------------------------------------------------------------------------
# _normalise_for_match
# ---------------------------------------------------------------------------


def test_normalise_lowercases():
    assert _normalise_for_match("XSS") == "xss"


def test_normalise_strips_spaces():
    assert _normalise_for_match("XSS Injection") == "xssinjection"


def test_normalise_strips_hyphens_underscores():
    assert _normalise_for_match("XSS-Injection_payloads") == "xssinjectionpayloads"


def test_normalise_handles_empty():
    assert _normalise_for_match("") == ""
    assert _normalise_for_match("   ") == ""
    assert _normalise_for_match("---___") == ""


# ---------------------------------------------------------------------------
# _score_repo_path
# ---------------------------------------------------------------------------


def test_score_top_level_readme_wins():
    """`XSS Injection/README.md` beats `Other/xss-notes.md`."""
    a = _score_repo_path(
        "XSS Injection/README.md",
        _normalise_for_match("XSS Injection/README.md"),
        "xss",
    )
    b = _score_repo_path(
        "Other/xss-notes.md",
        _normalise_for_match("Other/xss-notes.md"),
        "xss",
    )
    assert a > b


def test_score_drops_images():
    s = _score_repo_path(
        "XSS Injection/diagram.png",
        _normalise_for_match("XSS Injection/diagram.png"),
        "xss",
    )
    assert s == 0


def test_score_drops_binaries():
    for ext in (".exe", ".dll", ".so", ".zip", ".tar.gz"):
        path = f"XSS/payload{ext}"
        assert _score_repo_path(path, _normalise_for_match(path), "xss") == 0


def test_score_returns_zero_when_no_match():
    s = _score_repo_path(
        "SSRF/README.md", _normalise_for_match("SSRF/README.md"), "xss",
    )
    assert s == 0


def test_score_depth_penalty():
    shallow = _score_repo_path(
        "xss/README.md", _normalise_for_match("xss/README.md"), "xss",
    )
    deep = _score_repo_path(
        "a/b/c/d/xss/README.md",
        _normalise_for_match("a/b/c/d/xss/README.md"),
        "xss",
    )
    assert shallow > deep


# ---------------------------------------------------------------------------
# github_repo_search end-to-end (mocked httpx)
# ---------------------------------------------------------------------------


@pytest.fixture
def tools(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    config = AppConfig(llm=LLMConfig())
    state = StateStore(tmp_path)
    loader = SkillLoader(SKILLS_DIR)
    return Tools(config, state, loader)


def _fake_tree_response(paths: list[str], truncated: bool = False) -> MagicMock:
    """Build a httpx.Response-like object for the tree endpoint."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "tree": [
            {"path": p, "type": "blob", "sha": "abc"}
            for p in paths
        ],
        "truncated": truncated,
    }
    return resp


def test_search_rejects_non_github_url(tools):
    result = tools.github_repo_search("https://gitlab.com/x/y", "xss")
    assert "error" in result
    assert "Not a recognizable GitHub repo URL" in result["error"]


def test_search_rejects_empty_bug_class(tools):
    with patch.object(httpx, "Client"):
        result = tools.github_repo_search(
            "https://github.com/owner/repo", "   ",
        )
    assert "error" in result


def test_search_returns_ranked_paths(tools):
    fake_paths = [
        "XSS Injection/README.md",
        "XSS Injection/Files/payload.svg",  # image — drop
        "XSS Injection/Intruders/list.txt",
        "SSRF/README.md",
        "Prototype Pollution/README.md",
        "README.md",  # root readme — not bug-class-relevant
    ]
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get.return_value = _fake_tree_response(fake_paths)
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = tools.github_repo_search(
            "https://github.com/swisskyrepo/PayloadsAllTheThings",
            "xss",
        )

    assert "results" in result
    assert result["repo"] == "swisskyrepo/PayloadsAllTheThings"
    assert result["bug_class"] == "xss"
    paths = [r["path"] for r in result["results"]]
    # The XSS-related paths should be returned (in descending score)
    assert "XSS Injection/README.md" in paths
    # Top-level XSS README should be first
    assert paths[0] == "XSS Injection/README.md"
    # SVG / SSRF / Prototype Pollution must be dropped
    assert "XSS Injection/Files/payload.svg" not in paths
    assert "SSRF/README.md" not in paths
    assert "Prototype Pollution/README.md" not in paths


def test_search_builds_blob_and_raw_urls(tools):
    fake_paths = ["XSS Injection/README.md"]
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get.return_value = _fake_tree_response(fake_paths)
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = tools.github_repo_search(
            "https://github.com/swisskyrepo/PayloadsAllTheThings",
            "xss",
        )

    r = result["results"][0]
    assert r["blob_url"] == (
        "https://github.com/swisskyrepo/PayloadsAllTheThings/blob/HEAD/"
        "XSS%20Injection/README.md"
    )
    assert r["raw_url"] == (
        "https://raw.githubusercontent.com/swisskyrepo/PayloadsAllTheThings/"
        "HEAD/XSS%20Injection/README.md"
    )


def test_search_respects_limit(tools):
    paths = [f"XSS/file{i:03d}.md" for i in range(40)]
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get.return_value = _fake_tree_response(paths)
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = tools.github_repo_search(
            "https://github.com/owner/repo", "xss", limit=5,
        )

    assert len(result["results"]) == 5
    assert result["matched_count"] == 40
    assert result["returned_count"] == 5


def test_search_limit_capped_at_25(tools):
    paths = [f"XSS/file{i:03d}.md" for i in range(40)]
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get.return_value = _fake_tree_response(paths)
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = tools.github_repo_search(
            "https://github.com/owner/repo", "xss", limit=100,
        )
    assert len(result["results"]) == 25


def test_search_handles_404(tools):
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = tools.github_repo_search(
            "https://github.com/owner/nonexistent", "xss",
        )
    assert "error" in result
    assert "not found" in result["error"].lower()


def test_search_handles_403_rate_limit(tools):
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "rate limit"
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = tools.github_repo_search(
            "https://github.com/owner/repo", "xss",
        )
    assert "error" in result
    assert "GITHUB_TOKEN" in result["error"]


def test_search_uses_github_token_when_present(tools, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_testtoken123")
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get.return_value = _fake_tree_response(["XSS/README.md"])
        mock_client_cls.return_value.__enter__.return_value = mock_client

        tools.github_repo_search(
            "https://github.com/owner/repo", "xss",
        )

    # Verify the Authorization header was set
    headers_passed = mock_client_cls.call_args.kwargs.get("headers", {})
    assert headers_passed.get("Authorization") == "Bearer ghp_testtoken123"


def test_search_omits_authorization_when_no_token(tools):
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get.return_value = _fake_tree_response(["XSS/README.md"])
        mock_client_cls.return_value.__enter__.return_value = mock_client

        tools.github_repo_search(
            "https://github.com/owner/repo", "xss",
        )

    headers_passed = mock_client_cls.call_args.kwargs.get("headers", {})
    assert "Authorization" not in headers_passed


def test_search_dispatchable_via_tools_dispatch(tools):
    """Ensure github_repo_search is wired into Tools.dispatch."""
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get.return_value = _fake_tree_response(["XSS/README.md"])
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = tools.dispatch("github_repo_search", {
            "repo_url": "https://github.com/owner/repo",
            "bug_class": "xss",
        })
    assert "results" in result
    assert result["bug_class"] == "xss"


def test_search_handles_truncated_response(tools, caplog):
    fake_paths = ["XSS/README.md"]
    with patch("guide_agent.agent.tools.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get.return_value = _fake_tree_response(
            fake_paths, truncated=True,
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        with caplog.at_level("WARNING"):
            result = tools.github_repo_search(
                "https://github.com/owner/big-repo", "xss",
            )
    # Still returns results
    assert "results" in result
    # Warning logged
    assert any("truncated" in r.message.lower() for r in caplog.records)
