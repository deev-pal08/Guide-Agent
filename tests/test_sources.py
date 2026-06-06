"""Tests for source helpers — hardcoded pool rendering and web availability."""

from __future__ import annotations

from guide_agent.config import SearchConfig, SourceConfig, SourcesConfig
from guide_agent.sources.hardcoded import hardcoded_domains, render_hardcoded_pool
from guide_agent.sources.web import render_web_search_availability


def _sources_fixture() -> SourcesConfig:
    return SourcesConfig(
        learn=[
            SourceConfig(name="HackTricks", base_url="https://book.hacktricks.wiki/"),
            SourceConfig(name="PortSwigger Academy", base_url="https://portswigger.net/web-security"),
        ],
        examples=[
            SourceConfig(name="HackerOne Hacktivity", base_url="https://hackerone.com/hacktivity"),
        ],
        practice=[],
    )


# ---------------------------------------------------------------------------
# hardcoded.py
# ---------------------------------------------------------------------------


def test_render_hardcoded_pool_lists_all_sources():
    out = render_hardcoded_pool(_sources_fixture(), "learn")
    assert "HackTricks" in out
    assert "PortSwigger Academy" in out
    assert "book.hacktricks.wiki" in out


def test_render_hardcoded_pool_empty_for_phase_with_no_pool():
    out = render_hardcoded_pool(_sources_fixture(), "practice")
    assert out == ""


def test_render_hardcoded_pool_empty_for_unknown_phase():
    out = render_hardcoded_pool(_sources_fixture(), "execute")
    # execute isn't a SourcesConfig field — should still return empty cleanly
    assert out == ""


def test_render_hardcoded_pool_includes_phase_name_in_header():
    out = render_hardcoded_pool(_sources_fixture(), "examples")
    assert "examples" in out.lower()


def test_hardcoded_domains_returns_just_urls():
    domains = hardcoded_domains(_sources_fixture(), "learn")
    assert domains == [
        "https://book.hacktricks.wiki/",
        "https://portswigger.net/web-security",
    ]


def test_hardcoded_domains_empty_for_empty_pool():
    assert hardcoded_domains(_sources_fixture(), "practice") == []


# ---------------------------------------------------------------------------
# deep_urls
# ---------------------------------------------------------------------------


def test_deep_urls_returned_when_bug_class_matches():
    cfg = SourcesConfig(
        learn=[SourceConfig(name="HT", base_url="https://hacktricks.wiki/")],
        deep_urls={
            "learn": {
                "postmessage": [
                    "https://hacktricks.wiki/postmessage",
                    "https://portswigger.net/web-security/dom-based/web-message-manipulation",
                ],
            },
        },
    )
    out = render_hardcoded_pool(cfg, "learn", "postmessage")
    assert "Predeclared deep URLs" in out
    assert "https://hacktricks.wiki/postmessage" in out
    assert "https://portswigger.net/web-security/dom-based/web-message-manipulation" in out


def test_deep_urls_normalised_case_insensitive():
    cfg = SourcesConfig(
        deep_urls={"learn": {"postmessage": ["https://example.com/pm"]}},
    )
    out = render_hardcoded_pool(cfg, "learn", "PostMessage")
    assert "https://example.com/pm" in out


def test_deep_urls_skipped_when_no_match_for_bug_class():
    cfg = SourcesConfig(
        learn=[SourceConfig(name="HT", base_url="https://hacktricks.wiki/")],
        deep_urls={"learn": {"ssrf": ["https://example.com/ssrf"]}},
    )
    out = render_hardcoded_pool(cfg, "learn", "postmessage")
    assert "Predeclared deep URLs" not in out
    assert "https://example.com/ssrf" not in out
    # Pool still rendered
    assert "https://hacktricks.wiki/" in out


def test_deep_urls_skipped_when_bug_class_empty():
    cfg = SourcesConfig(
        learn=[SourceConfig(name="HT", base_url="https://hacktricks.wiki/")],
        deep_urls={"learn": {"postmessage": ["https://example.com/pm"]}},
    )
    out = render_hardcoded_pool(cfg, "learn", "")
    assert "Predeclared deep URLs" not in out


def test_deep_urls_only_renders_when_pool_missing_too():
    cfg = SourcesConfig(
        learn=[],
        deep_urls={"learn": {"postmessage": ["https://example.com/pm"]}},
    )
    out = render_hardcoded_pool(cfg, "learn", "postmessage")
    # No pool header, but deep URLs still rendered
    assert "Hardcoded sources" not in out
    assert "Predeclared deep URLs" in out
    assert "https://example.com/pm" in out


def test_get_deep_urls_helper_returns_list():
    cfg = SourcesConfig(
        deep_urls={"learn": {"postmessage": ["a", "b"]}},
    )
    assert cfg.get_deep_urls("learn", "postmessage") == ["a", "b"]
    assert cfg.get_deep_urls("learn", "PostMessage") == ["a", "b"]
    assert cfg.get_deep_urls("learn", "ssrf") == []
    assert cfg.get_deep_urls("practice", "postmessage") == []


# ---------------------------------------------------------------------------
# web.py
# ---------------------------------------------------------------------------


def test_render_web_search_availability_all_providers_enabled():
    cfg = SearchConfig()
    out = render_web_search_availability(cfg)
    assert "Brave" in out
    assert "Tavily" in out
    assert "Exa" in out


def test_render_web_search_availability_disabled():
    cfg = SearchConfig(enabled=False)
    out = render_web_search_availability(cfg)
    assert "DISABLED" in out


def test_render_web_search_availability_partial():
    cfg = SearchConfig()
    cfg.tavily.enabled = False
    cfg.exa.enabled = False
    out = render_web_search_availability(cfg)
    assert "Brave" in out
    assert "Tavily" not in out
    assert "Exa" not in out
