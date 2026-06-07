"""Tests for blog_feed_search — RSS + Atom parsing + search behavior."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

import guide_agent.agent.tools as tools_mod
from guide_agent.agent.tools import Tools, _clean_summary, _parse_feed_xml
from guide_agent.config import AppConfig, LLMConfig
from guide_agent.skills.loader import SkillLoader
from guide_agent.state.store import StateStore

SKILLS_DIR = "src/guide_agent/skills"


# ---------------------------------------------------------------------------
# _parse_feed_xml — RSS 2.0
# ---------------------------------------------------------------------------


RSS_SAMPLE = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Sample</title>
    <item>
      <title>SSRF in foo</title>
      <link>https://example.com/ssrf-foo</link>
      <description>An SSRF writeup about foo.</description>
      <pubDate>Mon, 01 Jan 2025 00:00:00 GMT</pubDate>
    </item>
    <item>
      <title>XSS via postMessage</title>
      <link>https://example.com/xss-pm</link>
      <description>Stored XSS triggered via postMessage handler.</description>
      <pubDate>Tue, 02 Jan 2025 00:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


def test_parse_rss_extracts_entries():
    entries = _parse_feed_xml(RSS_SAMPLE)
    assert len(entries) == 2
    titles = [e["title"] for e in entries]
    assert "SSRF in foo" in titles
    assert "XSS via postMessage" in titles
    first = next(e for e in entries if e["title"] == "SSRF in foo")
    assert first["link"] == "https://example.com/ssrf-foo"
    assert "SSRF" in first["summary"]
    assert "2025" in first["published"]


# ---------------------------------------------------------------------------
# _parse_feed_xml — Atom 1.0
# ---------------------------------------------------------------------------


ATOM_SAMPLE = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Sample Atom</title>
  <entry>
    <title>Wormable XSS on HackMD</title>
    <link href="https://blog.example.com/wormable-xss"/>
    <summary>How a wormable XSS was found on HackMD.</summary>
    <published>2019-03-15T00:00:00Z</published>
  </entry>
  <entry>
    <title>SSRF chain at GitHub Enterprise</title>
    <link href="https://blog.example.com/gh-ssrf"/>
    <summary>From SSRF to RCE in 4 bugs.</summary>
    <updated>2017-07-01T00:00:00Z</updated>
  </entry>
</feed>
"""


def test_parse_atom_extracts_entries():
    entries = _parse_feed_xml(ATOM_SAMPLE)
    assert len(entries) == 2
    titles = [e["title"] for e in entries]
    assert "Wormable XSS on HackMD" in titles
    assert "SSRF chain at GitHub Enterprise" in titles
    xss = next(e for e in entries if "Wormable" in e["title"])
    assert xss["link"] == "https://blog.example.com/wormable-xss"
    assert "wormable XSS" in xss["summary"]
    assert "2019" in xss["published"]


def test_parse_atom_falls_back_to_updated_when_no_published():
    entries = _parse_feed_xml(ATOM_SAMPLE)
    gh = next(e for e in entries if "GitHub" in e["title"])
    assert "2017" in gh["published"]


def test_parse_handles_bad_xml():
    with pytest.raises(ValueError):
        _parse_feed_xml("<<not xml>>")


# ---------------------------------------------------------------------------
# blog_feed_search end-to-end (mocked loader)
# ---------------------------------------------------------------------------


SAMPLE_ENTRIES = [
    {
        "title": "Wormable XSS on HackMD",
        "link": "https://blog.example.com/wormable-xss",
        "summary": "How a wormable XSS was found on HackMD.",
        "published": "2019-03-15",
    },
    {
        "title": "SSRF chain at GitHub Enterprise",
        "link": "https://blog.example.com/gh-ssrf",
        "summary": "From SSRF to RCE in 4 bugs.",
        "published": "2017-07-01",
    },
    {
        "title": "DOM XSS via postMessage handler",
        "link": "https://blog.example.com/dom-xss-pm",
        "summary": "postMessage origin not validated.",
        "published": "2024-08-01",
    },
    {
        "title": "Off-topic AI musings",
        "link": "https://blog.example.com/ai",
        "summary": "No security here.",
        "published": "2024-09-01",
    },
]


@pytest.fixture
def tools(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    config = AppConfig(llm=LLMConfig())
    state = StateStore(tmp_path)
    loader = SkillLoader(SKILLS_DIR)
    # Reset feed cache each test
    tools_mod._feed_cache = {}
    return Tools(config, state, loader)


@pytest.fixture
def patched_loader():
    with patch.object(tools_mod, "_load_blog_feed_entries",
                      return_value=SAMPLE_ENTRIES) as m:
        yield m


def test_search_rejects_empty_feed_url(tools):
    result = tools.blog_feed_search(feed_url="", bug_class="xss")
    assert "error" in result


def test_search_rejects_non_http_feed_url(tools):
    result = tools.blog_feed_search(feed_url="ftp://foo", bug_class="xss")
    assert "error" in result


def test_search_rejects_empty_bug_class(tools):
    result = tools.blog_feed_search(
        feed_url="https://example.com/feed", bug_class="   ",
    )
    assert "error" in result


def test_search_filters_by_title_substring(tools, patched_loader):
    result = tools.blog_feed_search(
        feed_url="https://example.com/feed", bug_class="xss",
    )
    titles = [r["title"] for r in result["results"]]
    assert "Wormable XSS on HackMD" in titles
    assert "DOM XSS via postMessage handler" in titles
    assert "Off-topic AI musings" not in titles


def test_search_filters_by_summary_substring(tools, patched_loader):
    # 'origin' only appears in summary, not title
    result = tools.blog_feed_search(
        feed_url="https://example.com/feed", bug_class="origin",
    )
    titles = [r["title"] for r in result["results"]]
    assert titles == ["DOM XSS via postMessage handler"]


def test_search_or_synonyms_via_pipe(tools, patched_loader):
    # SSRF OR postMessage
    result = tools.blog_feed_search(
        feed_url="https://example.com/feed", bug_class="ssrf|postmessage",
    )
    titles = [r["title"] for r in result["results"]]
    assert "SSRF chain at GitHub Enterprise" in titles
    assert "DOM XSS via postMessage handler" in titles
    assert "Off-topic AI musings" not in titles


def test_search_respects_limit(tools, patched_loader):
    result = tools.blog_feed_search(
        feed_url="https://example.com/feed", bug_class="xss", limit=1,
    )
    assert len(result["results"]) == 1
    assert result["total_count"] == 2
    assert result["returned_count"] == 1


def test_search_limit_capped_at_100(tools, patched_loader):
    result = tools.blog_feed_search(
        feed_url="https://example.com/feed", bug_class="xss", limit=9999,
    )
    assert len(result["results"]) <= 100


def test_search_truncates_summary(tools):
    long_entries = [{
        "title": "XSS bug",
        "link": "https://e.com/1",
        "summary": "x" * 1000,
        "published": "2024-01-01",
    }]
    with patch.object(tools_mod, "_load_blog_feed_entries",
                      return_value=long_entries):
        result = tools.blog_feed_search(
            feed_url="https://e.com/f", bug_class="xss",
        )
    assert len(result["results"][0]["summary"]) == 300


def test_search_handles_fetch_failure(tools):
    with patch.object(tools_mod, "_load_blog_feed_entries",
                      side_effect=httpx.ConnectError("nope")):
        result = tools.blog_feed_search(
            feed_url="https://e.com/f", bug_class="xss",
        )
    assert "error" in result


def test_search_dispatchable(tools, patched_loader):
    result = tools.dispatch("blog_feed_search", {
        "feed_url": "https://example.com/feed",
        "bug_class": "xss",
        "limit": 2,
    })
    assert "results" in result


def test_loader_caches_per_feed_url(tools):
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.text = RSS_SAMPLE

    call_count = {"n": 0}

    def fake_get(*a, **kw):
        call_count["n"] += 1
        return fake_resp

    fake_client = MagicMock()
    fake_client.get = fake_get
    with patch.object(tools_mod.httpx, "Client") as mock_cls:
        mock_cls.return_value.__enter__.return_value = fake_client

        tools.blog_feed_search(feed_url="https://e.com/f", bug_class="ssrf")
        # Same feed_url -> cache hit
        tools.blog_feed_search(feed_url="https://e.com/f", bug_class="xss")
        # Different feed_url -> new fetch
        tools.blog_feed_search(feed_url="https://e.com/g", bug_class="xss")

    assert call_count["n"] == 2


# ---------------------------------------------------------------------------
# HTML stripping in summary
# ---------------------------------------------------------------------------


def test_clean_summary_strips_html_tags():
    assert _clean_summary("<p>hello <b>world</b></p>") == "hello world"


def test_clean_summary_collapses_whitespace():
    assert _clean_summary("  too   many\n\nspaces  ") == "too many spaces"


def test_clean_summary_caps_length():
    huge = "<p>" + ("x" * 10000) + "</p>"
    assert len(_clean_summary(huge, max_len=500)) == 500


def test_clean_summary_handles_empty():
    assert _clean_summary("") == ""
    assert _clean_summary(None) == ""  # type: ignore[arg-type]


def test_parse_atom_strips_html_in_summary():
    atom = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Post</title>
    <link href="https://e.com/post"/>
    <summary>&lt;p&gt;Real XSS finding here.&lt;/p&gt;</summary>
  </entry>
</feed>
"""
    entries = _parse_feed_xml(atom)
    # The XML decoder will give us <p>Real XSS finding here.</p>, then strip
    assert "<" not in entries[0]["summary"]
    assert "Real XSS finding here." in entries[0]["summary"]


# ---------------------------------------------------------------------------
# Link rel preference
# ---------------------------------------------------------------------------


def test_parse_atom_prefers_alternate_link_rel():
    """When multiple <link> tags exist, prefer rel='alternate' (canonical post)."""
    atom = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Post</title>
    <link rel="self" href="https://e.com/feeds/self"/>
    <link rel="alternate" href="https://e.com/2025/the-real-post.html"/>
    <link rel="replies" href="https://e.com/feeds/replies"/>
    <summary>Summary</summary>
  </entry>
</feed>
"""
    entries = _parse_feed_xml(atom)
    assert entries[0]["link"] == "https://e.com/2025/the-real-post.html"


def test_parse_atom_falls_back_to_first_link_when_no_alternate():
    atom = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Post</title>
    <link rel="self" href="https://e.com/feeds/self"/>
    <summary>Summary</summary>
  </entry>
</feed>
"""
    entries = _parse_feed_xml(atom)
    assert entries[0]["link"] == "https://e.com/feeds/self"


# ---------------------------------------------------------------------------
# Blogger pagination routing
# ---------------------------------------------------------------------------


def test_loader_uses_paginator_for_blogspot_urls():
    """Blogspot feed URLs route through the paginator, not single-fetch."""
    fake_entries = [
        {"title": "p1", "link": "u1", "summary": "", "published": ""},
    ]
    with patch.object(
        tools_mod, "_fetch_blogger_paginated", return_value=fake_entries,
    ) as paginated, patch.object(tools_mod, "_fetch_feed_xml") as single:
        tools_mod._feed_cache = {}
        entries = tools_mod._load_blog_feed_entries(
            "https://example.blogspot.com/feeds/posts/default",
        )
        paginated.assert_called_once()
        single.assert_not_called()
        assert len(entries) == 1


def test_loader_uses_single_fetch_for_normal_feeds():
    with patch.object(tools_mod, "_fetch_feed_xml",
                      return_value=RSS_SAMPLE) as single, \
         patch.object(tools_mod, "_fetch_blogger_paginated") as paginated:
        tools_mod._feed_cache = {}
        entries = tools_mod._load_blog_feed_entries(
            "https://blog.example.com/atom.xml",
        )
        single.assert_called_once()
        paginated.assert_not_called()
        assert len(entries) == 2
