"""Tests for per-bug-class prefetch storage + retrieval."""

from __future__ import annotations

import pytest

from guide_agent.config import AppConfig, LLMConfig
from guide_agent.skills.loader import SkillLoader
from guide_agent.state.store import StateStore

SKILLS_DIR = "src/guide_agent/skills"


@pytest.fixture
def state(tmp_path):
    return StateStore(tmp_path)


@pytest.fixture
def tools(tmp_path, monkeypatch):
    from guide_agent.agent.tools import Tools
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    config = AppConfig(llm=LLMConfig())
    s = StateStore(tmp_path)
    loader = SkillLoader(SKILLS_DIR)
    return Tools(config, s, loader), s


# ---------------------------------------------------------------------------
# add_resources_for_bug_class
# ---------------------------------------------------------------------------


def test_add_inserts_and_tags(state):
    r = state.add_resources_for_bug_class("hacktivity", "postmessage", [
        {"url": "https://h1/1", "title": "DOM XSS via postMessage",
         "summary": "sev=High bounty=$1000", "metadata": {"bounty": 1000}},
        {"url": "https://h1/2", "title": "postMessage origin bypass",
         "summary": "sev=Critical bounty=$5000"},
    ])
    assert r == {"inserted": 2, "tagged": 2, "skipped": 0, "total": 2}
    assert state.tagged_count_for_bug_class("postmessage") == 2


def test_add_skips_blank_urls(state):
    r = state.add_resources_for_bug_class("x", "xss", [
        {"url": "", "title": "blank"},
        {"url": "https://a/1", "title": "good"},
    ])
    assert r["skipped"] == 1
    assert r["inserted"] == 1


def test_add_dedupes_url_across_sources(state):
    """Same URL fetched from two sources tags both but only inserts once."""
    state.add_resources_for_bug_class("hacktivity", "xss", [
        {"url": "https://shared/1", "title": "from h1"},
    ])
    r = state.add_resources_for_bug_class("pentesterland", "xss", [
        {"url": "https://shared/1", "title": "from ptl"},
    ])
    # URL exists -> inserted=0, but tag was already present so tagged=0 too
    assert r["inserted"] == 0
    assert r["tagged"] == 0

    rows = state._conn.execute(
        "SELECT COUNT(*) AS c FROM prefetched_resources WHERE url = ?",
        ("https://shared/1",),
    ).fetchone()
    assert rows["c"] == 1


def test_add_tags_same_url_for_two_bug_classes(state):
    """A URL relevant to two classes (xss + postmessage) gets both tags."""
    state.add_resources_for_bug_class("h1", "xss", [
        {"url": "https://h1/1", "title": "DOM XSS via postMessage"},
    ])
    r = state.add_resources_for_bug_class("h1", "postmessage", [
        {"url": "https://h1/1", "title": "DOM XSS via postMessage"},
    ])
    assert r["tagged"] == 1  # tag added for postmessage
    assert state.tagged_count_for_bug_class("xss") == 1
    assert state.tagged_count_for_bug_class("postmessage") == 1


def test_add_normalizes_bug_class_case(state):
    state.add_resources_for_bug_class("x", "PostMessage", [
        {"url": "https://a/1", "title": "t"},
    ])
    # Stored lowercase
    assert state.tagged_count_for_bug_class("postmessage") == 1
    assert state.tagged_count_for_bug_class("PostMessage") == 1


# ---------------------------------------------------------------------------
# query_prefetched
# ---------------------------------------------------------------------------


def _seed(state):
    state.add_resources_for_bug_class("hacktivity", "xss", [
        {"url": "https://h/1", "title": "Stored XSS", "summary": ""},
        {"url": "https://h/2", "title": "Reflected XSS", "summary": ""},
    ])
    state.add_resources_for_bug_class("pentesterland", "xss", [
        {"url": "https://p/1", "title": "Apple XSS bounty"},
    ])
    state.add_resources_for_bug_class("hacktivity", "ssrf", [
        {"url": "https://h/3", "title": "Blind SSRF"},
    ])


def test_query_returns_only_tagged_class(state):
    _seed(state)
    r = state.query_prefetched("xss")
    urls = [x["url"] for x in r["results"]]
    assert "https://h/1" in urls
    assert "https://h/2" in urls
    assert "https://p/1" in urls
    assert "https://h/3" not in urls


def test_query_filters_by_source(state):
    _seed(state)
    r = state.query_prefetched("xss", source="hacktivity")
    sources = {x["source"] for x in r["results"]}
    assert sources == {"hacktivity"}


def test_query_excludes_consumed(state):
    _seed(state)
    bc_id = state.upsert_bug_class("xss")
    state.mark_consumed(
        bug_class_id=bc_id, url="https://h/1",
        phase="examples", title="Stored XSS",
    )
    r = state.query_prefetched("xss", bug_class_id=bc_id)
    urls = [x["url"] for x in r["results"]]
    assert "https://h/1" not in urls
    assert "https://h/2" in urls
    assert r["excluded_count"] == 1


def test_query_respects_limit(state):
    state.add_resources_for_bug_class("h", "xss", [
        {"url": f"https://h/{i}", "title": f"XSS bug {i}"}
        for i in range(30)
    ])
    r = state.query_prefetched("xss", limit=5)
    assert r["returned_count"] == 5
    assert r["total_tagged"] == 30


def test_query_limit_capped_at_200(state):
    state.add_resources_for_bug_class("h", "xss", [
        {"url": f"https://h/{i}", "title": f"XSS {i}"}
        for i in range(300)
    ])
    r = state.query_prefetched("xss", limit=9999)
    assert r["returned_count"] == 200


def test_query_rejects_empty_bug_class(state):
    r = state.query_prefetched("   ")
    assert "error" in r


# ---------------------------------------------------------------------------
# unread_count_for_bug_class
# ---------------------------------------------------------------------------


def test_unread_count_reflects_consumed(state):
    state.add_resources_for_bug_class("h", "xss", [
        {"url": f"https://h/{i}", "title": f"XSS {i}"} for i in range(5)
    ])
    bc_id = state.upsert_bug_class("xss")
    assert state.unread_count_for_bug_class("xss", bc_id) == 5

    state.mark_consumed(bc_id, "https://h/0", phase="examples")
    state.mark_consumed(bc_id, "https://h/1", phase="examples")
    assert state.unread_count_for_bug_class("xss", bc_id) == 3


def test_unread_count_empty_for_new_class(state):
    bc_id = state.upsert_bug_class("never-fetched")
    assert state.unread_count_for_bug_class("never-fetched", bc_id) == 0


# ---------------------------------------------------------------------------
# Tool wrapper still works
# ---------------------------------------------------------------------------


def test_tool_wrapper_returns_same_shape(tools):
    t, s = tools
    s.add_resources_for_bug_class("h", "xss", [
        {"url": "https://a/1", "title": "XSS bug"},
    ])
    bc_id = s.upsert_bug_class("xss")
    r = t.prefetched_resource_search(bug_class="xss", bug_class_id=bc_id)
    assert "results" in r
    assert r["returned_count"] == 1
    assert r["results"][0]["url"] == "https://a/1"


def test_tool_dispatchable(tools):
    t, s = tools
    s.add_resources_for_bug_class("h", "xss", [
        {"url": "https://a/1", "title": "XSS"},
    ])
    r = t.dispatch("prefetched_resource_search", {"bug_class": "xss"})
    assert "results" in r
