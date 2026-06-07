"""Tests for sitemap_search — XML parsing + URL filtering."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

import guide_agent.agent.tools as tools_mod
from guide_agent.agent.tools import Tools, _parse_sitemap_xml
from guide_agent.config import AppConfig, LLMConfig
from guide_agent.skills.loader import SkillLoader
from guide_agent.state.store import StateStore

SKILLS_DIR = "src/guide_agent/skills"


# ---------------------------------------------------------------------------
# _parse_sitemap_xml — urlset
# ---------------------------------------------------------------------------


URLSET_SAMPLE = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://example.com/blog/post-1/</loc>
    <lastmod>2025-01-01</lastmod>
  </url>
  <url>
    <loc>https://example.com/blog/xss-in-app/</loc>
  </url>
</urlset>
"""


def test_parse_urlset_extracts_locs():
    sub_sms, urls = _parse_sitemap_xml(URLSET_SAMPLE)
    assert sub_sms == []
    assert "https://example.com/blog/post-1/" in urls
    assert "https://example.com/blog/xss-in-app/" in urls


# ---------------------------------------------------------------------------
# _parse_sitemap_xml — sitemap index
# ---------------------------------------------------------------------------


INDEX_SAMPLE = """<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sitemap-1.xml</loc></sitemap>
  <sitemap><loc>https://example.com/sitemap-2.xml</loc></sitemap>
</sitemapindex>
"""


def test_parse_index_extracts_sub_sitemaps():
    sub_sms, urls = _parse_sitemap_xml(INDEX_SAMPLE)
    assert urls == []
    assert "https://example.com/sitemap-1.xml" in sub_sms
    assert "https://example.com/sitemap-2.xml" in sub_sms


def test_parse_handles_bad_xml():
    with pytest.raises(ValueError):
        _parse_sitemap_xml("<<not xml>>")


# ---------------------------------------------------------------------------
# sitemap_search end-to-end (mocked loader)
# ---------------------------------------------------------------------------


SAMPLE_URLS = [
    "https://sonarsource.com/",  # host contains 'rce' — must not match!
    "https://sonarsource.com/blog/",
    "https://sonarsource.com/blog/mxss-the-vulnerability/",
    "https://sonarsource.com/blog/wordpress-stored-xss/",
    "https://sonarsource.com/blog/limesurvey-xss-to-rce/",
    "https://sonarsource.com/blog/checkmk-rce-chain-1/",
    "https://sonarsource.com/blog/blitzjs-prototype-pollution/",
    "https://sonarsource.com/de/blog/translated-mirror/",
    "https://sonarsource.com/products/sonarqube/",
]


@pytest.fixture
def tools(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    config = AppConfig(llm=LLMConfig())
    state = StateStore(tmp_path)
    loader = SkillLoader(SKILLS_DIR)
    tools_mod._sitemap_cache = {}
    return Tools(config, state, loader)


@pytest.fixture
def patched_loader():
    with patch.object(tools_mod, "_load_sitemap_urls",
                      return_value=SAMPLE_URLS) as m:
        yield m


def test_search_rejects_empty_sitemap_url(tools):
    result = tools.sitemap_search(sitemap_url="", bug_class="xss")
    assert "error" in result


def test_search_rejects_non_http_sitemap_url(tools):
    result = tools.sitemap_search(sitemap_url="ftp://foo", bug_class="xss")
    assert "error" in result


def test_search_rejects_empty_bug_class(tools):
    result = tools.sitemap_search(
        sitemap_url="https://e.com/sm.xml", bug_class="",
    )
    assert "error" in result


def test_search_filters_by_substring(tools, patched_loader):
    result = tools.sitemap_search(
        sitemap_url="https://sonarsource.com/sitemap.xml",
        bug_class="xss",
    )
    urls = [r["url"] for r in result["results"]]
    assert "https://sonarsource.com/blog/mxss-the-vulnerability/" in urls
    assert "https://sonarsource.com/blog/wordpress-stored-xss/" in urls
    assert "https://sonarsource.com/blog/limesurvey-xss-to-rce/" in urls


def test_search_path_only_match_ignores_host_substring(tools, patched_loader):
    """'rce' is in 'sonarsource' host — must NOT match all URLs."""
    result = tools.sitemap_search(
        sitemap_url="https://sonarsource.com/sitemap.xml",
        bug_class="rce",
    )
    urls = [r["url"] for r in result["results"]]
    # Only checkmk-rce-chain-1 + limesurvey-xss-to-rce path-contains 'rce'
    assert "https://sonarsource.com/blog/checkmk-rce-chain-1/" in urls
    assert "https://sonarsource.com/blog/limesurvey-xss-to-rce/" in urls
    # The bare host URL must NOT match
    assert "https://sonarsource.com/" not in urls
    assert "https://sonarsource.com/blog/" not in urls


def test_search_or_synonyms(tools, patched_loader):
    result = tools.sitemap_search(
        sitemap_url="https://sonarsource.com/sitemap.xml",
        bug_class="xss|prototype-pollution",
    )
    urls = [r["url"] for r in result["results"]]
    assert any("xss" in u for u in urls)
    assert any("prototype-pollution" in u for u in urls)


def test_search_url_prefix_filter(tools, patched_loader):
    result = tools.sitemap_search(
        sitemap_url="https://sonarsource.com/sitemap.xml",
        bug_class="xss",
        url_prefix="https://sonarsource.com/blog/",  # excludes /de/
    )
    urls = [r["url"] for r in result["results"]]
    assert all(u.startswith("https://sonarsource.com/blog/") for u in urls)


def test_search_respects_limit(tools, patched_loader):
    result = tools.sitemap_search(
        sitemap_url="https://sonarsource.com/sitemap.xml",
        bug_class="xss",
        limit=1,
    )
    assert len(result["results"]) == 1


def test_search_limit_capped_at_100(tools, patched_loader):
    result = tools.sitemap_search(
        sitemap_url="https://sonarsource.com/sitemap.xml",
        bug_class="xss",
        limit=9999,
    )
    assert len(result["results"]) <= 100


def test_search_handles_fetch_failure(tools):
    with patch.object(tools_mod, "_load_sitemap_urls",
                      side_effect=httpx.ConnectError("nope")):
        result = tools.sitemap_search(
            sitemap_url="https://e.com/sm.xml", bug_class="xss",
        )
    assert "error" in result


def test_search_dispatchable(tools, patched_loader):
    result = tools.dispatch("sitemap_search", {
        "sitemap_url": "https://e.com/sm.xml",
        "bug_class": "xss",
        "limit": 5,
    })
    assert "results" in result


# ---------------------------------------------------------------------------
# Index walking
# ---------------------------------------------------------------------------


def test_walk_follows_sitemap_index():
    """A sitemap index should cause sub-sitemaps to be fetched + merged."""
    fetched = []

    def fake_fetch(url):
        fetched.append(url)
        if "index" in url:
            return INDEX_SAMPLE
        if "sitemap-1" in url:
            return """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/from-sub-1/</loc></url>
</urlset>"""
        if "sitemap-2" in url:
            return """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/from-sub-2/</loc></url>
</urlset>"""
        return ""

    with patch.object(tools_mod, "_fetch_feed_xml", side_effect=fake_fetch):
        tools_mod._sitemap_cache = {}
        urls = tools_mod._load_sitemap_urls("https://example.com/sitemap-index.xml")

    assert "https://example.com/from-sub-1/" in urls
    assert "https://example.com/from-sub-2/" in urls
    # 1 index + 2 sub-sitemaps fetched
    assert len(fetched) == 3


def test_walk_caps_at_max_depth():
    """Should not recurse forever if sitemaps reference each other."""
    cyclic = """<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/cyclic.xml</loc></sitemap>
</sitemapindex>
"""
    with patch.object(tools_mod, "_fetch_feed_xml", return_value=cyclic):
        tools_mod._sitemap_cache = {}
        urls = tools_mod._load_sitemap_urls("https://example.com/cyclic.xml")
    assert urls == []
