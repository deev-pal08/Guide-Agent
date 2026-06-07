"""Tests for per-bug-class fan-out fetcher."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from guide_agent import refresh as refresh_mod
from guide_agent.config import AppConfig, LLMConfig, SourceConfig, SourcesConfig
from guide_agent.state.store import StateStore


@pytest.fixture
def state(tmp_path):
    return StateStore(tmp_path)


@pytest.fixture
def config():
    return AppConfig(
        llm=LLMConfig(),
        sources=SourcesConfig(
            examples=[
                SourceConfig(
                    name="Orange Tsai",
                    base_url="https://blog.orange.tw/",
                    feed_url="https://blog.orange.tw/atom.xml",
                ),
                SourceConfig(
                    name="Sonar",
                    base_url="https://www.sonarsource.com/blog/",
                    sitemap_url="https://www.sonarsource.com/sitemap.xml",
                ),
                SourceConfig(
                    name="PayloadsAllTheThings",
                    base_url="https://github.com/swisskyrepo/PayloadsAllTheThings",
                ),
            ],
        ),
    )


def _mock_tools():
    """Build a Tools mock that returns one fake result per source method."""
    tools = MagicMock()
    tools.hackerone_hacktivity_search.return_value = {
        "results": [
            {"url": "https://h1/1", "title": "DOM XSS via postMessage",
             "severity": "High", "bounty": 1000, "cwe": "XSS",
             "team_handle": "shopify", "votes": 5, "report_id": "1"},
        ],
    }
    tools.pentesterland_search.return_value = {
        "results": [
            {"url": "https://ptl/1", "title": "Apple postMessage bug",
             "bounty": 5000, "authors": ["alice"], "programs": ["Apple"],
             "bugs": ["postMessage"], "publication_date": "2024-01-01"},
        ],
    }
    tools.ctfsearch_search.return_value = {
        "results": [
            {"url": "https://ctf/1", "title": "postMessage CTF challenge",
             "category": "Web", "date": "2024-01-01"},
        ],
    }
    tools.codereviewlab_search.return_value = {
        "results": [
            {"url": "https://www.codereviewlab.com/challenges/c1",
             "id": "c1", "title": "Stored XSS in profile",
             "vuln_type": "XSS (Cross-Site Scripting)", "language": "PHP",
             "difficulty": "EASY", "points": 100, "platform": "Web",
             "description": ""},
        ],
    }
    tools.blog_feed_search.return_value = {
        "results": [
            {"url": "https://feed/1", "title": "PostMessage on Orange's blog",
             "summary": "deep dive", "published": "2024-01-01"},
        ],
    }
    tools.sitemap_search.return_value = {
        "results": [
            {"url": "https://sm/1"},
        ],
    }
    tools.github_repo_search.return_value = {
        "results": [
            {"path": "PostMessage/README.md",
             "blob_url": "https://github.com/x/y/blob/HEAD/PostMessage/README.md",
             "raw_url": "https://raw.githubusercontent.com/x/y/HEAD/PostMessage/README.md"},
        ],
    }
    tools.web_search.return_value = {
        "results": [
            {"url": "https://web/1", "title": "postMessage writeup",
             "description": "blah", "source": "brave"},
        ],
    }
    tools.ctftime_events.return_value = {
        "results": [
            {"url": "https://ctftime.org/event/100/", "title": "Big CTF 2026",
             "format": "Jeopardy", "start": "2026-06-15T12:00:00+00:00",
             "finish": "2026-06-16T12:00:00+00:00",
             "restrictions": "Open", "weight": 50.0, "onsite": False,
             "duration": {"days": 1, "hours": 0}, "external_url": "https://ctf",
             "participants": 200},
        ],
    }
    tools.github_repos_by_stars.return_value = {
        "results": [
            {"url": "https://github.com/expressjs/express",
             "full_name": "expressjs/express",
             "description": "Node framework", "stars": 67000, "forks": 12000,
             "language": "JavaScript", "topics": ["nodejs", "framework"],
             "pushed_at": "2026-05-01T00:00:00Z", "license": "MIT",
             "archived": False},
        ],
    }
    return tools


# ---------------------------------------------------------------------------
# populate_for_bug_class
# ---------------------------------------------------------------------------


def test_populate_calls_all_universal_sources(config, state):
    tools = _mock_tools()
    report = refresh_mod.populate_for_bug_class(
        config, state, tools, bug_class="postmessage", phase="examples",
    )
    assert "hacktivity" in report
    assert "pentesterland" in report
    assert "ctfsearch" in report
    assert "web_search" in report
    tools.hackerone_hacktivity_search.assert_called()
    tools.pentesterland_search.assert_called()
    tools.ctfsearch_search.assert_called()
    tools.web_search.assert_called()


def test_populate_calls_per_source_feed_when_configured(config, state):
    tools = _mock_tools()
    report = refresh_mod.populate_for_bug_class(
        config, state, tools, bug_class="postmessage", phase="examples",
    )
    assert "feed:Orange Tsai" in report
    tools.blog_feed_search.assert_called_with(
        feed_url="https://blog.orange.tw/atom.xml",
        bug_class="postmessage",
        limit=50,
    )


def test_populate_calls_per_source_sitemap_when_configured(config, state):
    tools = _mock_tools()
    report = refresh_mod.populate_for_bug_class(
        config, state, tools, bug_class="postmessage", phase="examples",
    )
    assert "sitemap:Sonar" in report
    tools.sitemap_search.assert_called_with(
        sitemap_url="https://www.sonarsource.com/sitemap.xml",
        bug_class="postmessage",
        url_prefix="https://www.sonarsource.com/blog/",
        limit=100,
    )


def test_populate_calls_github_repo_search_for_github_sources(config, state):
    tools = _mock_tools()
    refresh_mod.populate_for_bug_class(
        config, state, tools, bug_class="xss", phase="examples",
    )
    # Adapter requests 3× limit to compensate for the .md-only filter
    # dropping non-doc paths during the refresh layer.
    tools.github_repo_search.assert_called_with(
        repo_url="https://github.com/swisskyrepo/PayloadsAllTheThings",
        bug_class="xss",
        limit=45,
    )


def test_populate_persists_results_tagged_with_bug_class(config, state):
    tools = _mock_tools()
    refresh_mod.populate_for_bug_class(
        config, state, tools, bug_class="postmessage", phase="examples",
    )
    # 8 mocked sources × 1 result each = 8 (hacktivity, pentesterland,
    # ctfsearch, codereviewlab, feed, sitemap, github, web_search)
    bc_id = state.upsert_bug_class("postmessage")
    r = state.query_prefetched("postmessage", bug_class_id=bc_id, limit=50)
    assert r["returned_count"] == 8
    sources = {x["source"] for x in r["results"]}
    assert sources == {
        "hacktivity", "pentesterland", "ctfsearch", "codereviewlab",
        "web_search", "feed:Orange Tsai", "sitemap:Sonar",
        "github:PayloadsAllTheThings",
    }


def test_populate_dedupes_repeated_endpoints(state):
    """If two phases reference the same feed, it's still only called once."""
    cfg = AppConfig(
        llm=LLMConfig(),
        sources=SourcesConfig(
            examples=[
                SourceConfig(
                    name="A", base_url="https://a.com/",
                    feed_url="https://a.com/feed",
                ),
                SourceConfig(
                    name="B", base_url="https://b.com/",
                    feed_url="https://a.com/feed",  # same feed
                ),
            ],
        ),
    )
    tools = _mock_tools()
    refresh_mod.populate_for_bug_class(
        cfg, state, tools, bug_class="xss", phase="examples",
    )
    # Only one blog_feed_search call (deduped by feed_url)
    assert tools.blog_feed_search.call_count == 1


def test_populate_handles_source_failure(config, state):
    tools = _mock_tools()
    tools.hackerone_hacktivity_search.return_value = {"error": "graphql died"}
    report = refresh_mod.populate_for_bug_class(
        config, state, tools, bug_class="xss", phase="examples",
    )
    # Failed source recorded with 0 counts, doesn't crash
    assert report["hacktivity"]["fetched"] == 0


# ---------------------------------------------------------------------------
# populate_if_empty (auto-trigger)
# ---------------------------------------------------------------------------


def test_populate_if_empty_skips_when_unread_exists(config, state):
    state.add_resources_for_bug_class("seed", "xss", [
        {"url": "https://existing/1", "title": "XSS"},
    ])
    bc_id = state.upsert_bug_class("xss")

    tools = _mock_tools()
    did_fetch, report = refresh_mod.populate_if_empty(
        config, state, tools,
        bug_class="xss", bug_class_id=bc_id, phase="examples",
    )
    assert did_fetch is False
    assert report == {}
    tools.hackerone_hacktivity_search.assert_not_called()


def test_populate_if_empty_fires_when_all_consumed(config, state):
    state.add_resources_for_bug_class("seed", "xss", [
        {"url": "https://existing/1", "title": "XSS"},
    ])
    bc_id = state.upsert_bug_class("xss")
    state.mark_consumed(bc_id, "https://existing/1", phase="examples")

    tools = _mock_tools()
    did_fetch, report = refresh_mod.populate_if_empty(
        config, state, tools,
        bug_class="xss", bug_class_id=bc_id, phase="examples",
    )
    assert did_fetch is True
    assert "hacktivity" in report
    tools.hackerone_hacktivity_search.assert_called()


def test_populate_if_empty_force_bypasses_check(config, state):
    """--fresh equivalent: always populate even when unread > 0."""
    state.add_resources_for_bug_class("seed", "xss", [
        {"url": "https://existing/1", "title": "XSS"},
    ])
    bc_id = state.upsert_bug_class("xss")

    tools = _mock_tools()
    did_fetch, report = refresh_mod.populate_if_empty(
        config, state, tools,
        bug_class="xss", bug_class_id=bc_id, phase="examples",
        force=True,
    )
    assert did_fetch is True
    tools.hackerone_hacktivity_search.assert_called()


def test_populate_if_empty_fires_for_brand_new_class(config, state):
    bc_id = state.upsert_bug_class("never-fetched")
    tools = _mock_tools()
    did_fetch, report = refresh_mod.populate_if_empty(
        config, state, tools,
        bug_class="never-fetched", bug_class_id=bc_id, phase="examples",
    )
    assert did_fetch is True


# ---------------------------------------------------------------------------
# Per-source adapter sanity (lightweight)
# ---------------------------------------------------------------------------


def test_fetch_hacktivity_propagates_metadata():
    tools = MagicMock()
    tools.hackerone_hacktivity_search.return_value = {
        "results": [
            {"url": "https://h/1", "title": "T", "severity": "Critical",
             "bounty": 5000, "cwe": "XSS", "team_handle": "shopify",
             "votes": 10, "report_id": "1"},
        ],
    }
    rows = refresh_mod.fetch_hacktivity_for_class(tools, "xss", limit=5)
    assert rows[0]["metadata"]["severity"] == "Critical"
    assert rows[0]["metadata"]["bounty"] == 5000


def test_fetch_web_search_dedupes_urls_across_queries():
    tools = MagicMock()
    tools.web_search.side_effect = [
        {"results": [{"url": "https://w/1", "title": "T1",
                      "description": "", "source": "brave"}]},
        {"results": [{"url": "https://w/1", "title": "T1 dup",
                      "description": "", "source": "tavily"}]},
        {"results": [{"url": "https://w/2", "title": "T2",
                      "description": "", "source": "brave"}]},
    ]
    rows = refresh_mod.fetch_web_search_for_class(
        tools, ["q1", "q2", "q3"],
    )
    urls = [r["url"] for r in rows]
    assert urls == ["https://w/1", "https://w/2"]


def test_fetch_swallows_tool_errors():
    tools = MagicMock()
    tools.pentesterland_search.return_value = {"error": "boom"}
    rows = refresh_mod.fetch_pentesterland_for_class(tools, ["xss"])
    assert rows == []


# ---------------------------------------------------------------------------
# Phase-aware source flagging
# ---------------------------------------------------------------------------


def test_learn_phase_skips_hacktivity_and_pentesterland(config, state):
    """learn = theory; writeups + disclosed reports must NOT fire."""
    tools = _mock_tools()
    refresh_mod.populate_for_bug_class(
        config, state, tools, bug_class="postmessage", phase="learn",
    )
    tools.hackerone_hacktivity_search.assert_not_called()
    tools.pentesterland_search.assert_not_called()
    tools.ctfsearch_search.assert_not_called()
    # web_search still fires for learn
    tools.web_search.assert_called()


def test_examples_phase_fires_all_universal_tools(config, state):
    """examples = writeups; every universal tool should fire."""
    tools = _mock_tools()
    refresh_mod.populate_for_bug_class(
        config, state, tools, bug_class="postmessage", phase="examples",
    )
    tools.hackerone_hacktivity_search.assert_called()
    tools.pentesterland_search.assert_called()
    tools.ctfsearch_search.assert_called()
    tools.codereviewlab_search.assert_called()
    tools.web_search.assert_called()


def test_practice_phase_fires_codereviewlab(config, state):
    """practice = labs; codereviewlab is on for source-review training."""
    tools = _mock_tools()
    refresh_mod.populate_for_bug_class(
        config, state, tools, bug_class="xss", phase="practice",
    )
    tools.codereviewlab_search.assert_called()


def test_learn_phase_skips_codereviewlab(config, state):
    """learn = theory; codereviewlab challenges (practice/examples) skipped."""
    tools = _mock_tools()
    refresh_mod.populate_for_bug_class(
        config, state, tools, bug_class="xss", phase="learn",
    )
    tools.codereviewlab_search.assert_not_called()


def test_practice_phase_skips_writeup_sources(config, state):
    """practice = labs; skip hacktivity + pentesterland but keep ctfsearch."""
    tools = _mock_tools()
    refresh_mod.populate_for_bug_class(
        config, state, tools, bug_class="postmessage", phase="practice",
    )
    tools.hackerone_hacktivity_search.assert_not_called()
    tools.pentesterland_search.assert_not_called()
    tools.ctfsearch_search.assert_called()  # CTF walkthroughs = pseudo-labs


def test_execute_phase_only_uses_web_search(config, state):
    """execute = live programs; only web_search fires for universal sources."""
    tools = _mock_tools()
    refresh_mod.populate_for_bug_class(
        config, state, tools, bug_class="postmessage", phase="execute",
    )
    tools.hackerone_hacktivity_search.assert_not_called()
    tools.pentesterland_search.assert_not_called()
    tools.ctfsearch_search.assert_not_called()
    tools.web_search.assert_called()


def test_phase_specific_web_queries_for_learn(config, state):
    """learn web queries should target tutorials / cheatsheets, not writeups."""
    tools = _mock_tools()
    refresh_mod.populate_for_bug_class(
        config, state, tools, bug_class="postmessage", phase="learn",
    )
    queries = [
        call.kwargs.get("query", call.args[0] if call.args else "")
        for call in tools.web_search.call_args_list
    ]
    joined = " ".join(queries).lower()
    assert "tutorial" in joined or "cheatsheet" in joined
    assert "writeup bug bounty" not in joined


def test_phase_specific_web_queries_for_execute(config, state):
    """execute web queries should target live programs."""
    tools = _mock_tools()
    refresh_mod.populate_for_bug_class(
        config, state, tools, bug_class="xss", phase="execute",
    )
    queries = [
        call.kwargs.get("query", call.args[0] if call.args else "")
        for call in tools.web_search.call_args_list
    ]
    joined = " ".join(queries).lower()
    assert "bug bounty program" in joined or "scope" in joined or "live" in joined


def test_unknown_phase_falls_back_to_examples_flags(config, state):
    """Defensive — an unknown phase string should behave like examples."""
    tools = _mock_tools()
    refresh_mod.populate_for_bug_class(
        config, state, tools, bug_class="xss", phase="bogus_phase",
    )
    tools.hackerone_hacktivity_search.assert_called()
    tools.pentesterland_search.assert_called()


# ---------------------------------------------------------------------------
# Execute-phase ambient discovery (CTFtime + popular OSS)
# ---------------------------------------------------------------------------


def test_execute_phase_fires_ctftime(config, state):
    tools = _mock_tools()
    refresh_mod.populate_for_bug_class(
        config, state, tools, bug_class="xss", phase="execute",
    )
    tools.ctftime_events.assert_called()


def test_execute_phase_fires_github_repos_by_stars(config, state):
    tools = _mock_tools()
    refresh_mod.populate_for_bug_class(
        config, state, tools, bug_class="xss", phase="execute",
    )
    tools.github_repos_by_stars.assert_called()


def test_execute_phase_passes_min_stars_floor(config, state):
    tools = _mock_tools()
    refresh_mod.populate_for_bug_class(
        config, state, tools, bug_class="xss", phase="execute",
    )
    # Popular OSS queries enforce 5000+ stars (Task 2 quality floor);
    # hunting-tool queries use 50+ stars (security tools are nicher).
    # Either floor is acceptable here; nothing should be unbounded.
    for call in tools.github_repos_by_stars.call_args_list:
        min_stars = call.kwargs.get("min_stars", 0)
        assert min_stars > 0, "every github_repos_by_stars call must set min_stars"


def test_execute_phase_fires_hunting_tools(config, state):
    """Tools Section gets populated via hunting-tool queries."""
    tools = _mock_tools()
    refresh_mod.populate_for_bug_class(
        config, state, tools, bug_class="xss", phase="execute",
    )
    # Inspect calls — at least one should be a hunting-tool query
    # (suffixed with scanner / exploitation / fuzzer / etc).
    queries = [c.kwargs.get("query", "") for c in tools.github_repos_by_stars.call_args_list]
    assert any(
        any(s in q for s in ["scanner", "exploitation", "fuzzer", "burp extension"])
        for q in queries
    )


def test_execute_phase_does_not_fire_hacktivity_or_ctfsearch(config, state):
    """Execute is AMBIENT — no per-bug-class trawling of writeup archives."""
    tools = _mock_tools()
    refresh_mod.populate_for_bug_class(
        config, state, tools, bug_class="xss", phase="execute",
    )
    tools.hackerone_hacktivity_search.assert_not_called()
    tools.pentesterland_search.assert_not_called()
    tools.ctfsearch_search.assert_not_called()


def test_other_phases_do_not_fire_ctftime_or_popular_oss(config, state):
    """ctftime + popular_oss are execute-only adapters."""
    for phase in ("learn", "examples", "practice"):
        tools = _mock_tools()
        refresh_mod.populate_for_bug_class(
            config, state, tools, bug_class="xss", phase=phase,
        )
        tools.ctftime_events.assert_not_called()
        tools.github_repos_by_stars.assert_not_called()


# ---------------------------------------------------------------------------
# Newsletter adapter (cross-agent integration)
# ---------------------------------------------------------------------------


def test_newsletter_fires_for_learn_and_examples(config, state):
    """Newsletter adapter is on for learn + examples, off for others."""
    config.newsletter.enabled = True
    config.newsletter.project_dir = "/tmp/fake_newsletter"

    fetched = {"called": []}

    def fake_fetch(config, bug_class, limit=200):
        fetched["called"].append(bug_class)
        return [{"url": f"https://nl/{bug_class}/1", "title": "T",
                 "summary": "", "metadata": {}}]

    with patch.object(refresh_mod, "fetch_newsletter_for_class", side_effect=fake_fetch):
        for phase in ("learn", "examples"):
            fetched["called"].clear()
            tools = _mock_tools()
            refresh_mod.populate_for_bug_class(
                config, state, tools, bug_class="xss", phase=phase,
            )
            assert "xss" in fetched["called"], f"newsletter not called for {phase}"

        for phase in ("practice", "execute"):
            fetched["called"].clear()
            tools = _mock_tools()
            refresh_mod.populate_for_bug_class(
                config, state, tools, bug_class="xss", phase=phase,
            )
            assert "xss" not in fetched["called"], (
                f"newsletter should NOT fire for {phase}"
            )


def test_newsletter_adapter_returns_empty_when_disabled(config):
    """Adapter is silent when newsletter integration is off."""
    config.newsletter.enabled = False
    rows = refresh_mod.fetch_newsletter_for_class(config, "xss")
    assert rows == []


def test_newsletter_adapter_returns_empty_when_db_missing(config):
    """Adapter is silent if the DB file doesn't exist."""
    config.newsletter.enabled = True
    config.newsletter.project_dir = "/nonexistent/path/no/way"
    rows = refresh_mod.fetch_newsletter_for_class(config, "xss")
    assert rows == []
