"""Tests for bug-class term expansion (Lever 3)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from guide_agent.agent.expansion import (
    ExpansionBrain,
    build_search_query,
    ensure_expansion,
)
from guide_agent.config import AppConfig, LLMConfig
from guide_agent.skills.loader import SkillLoader
from guide_agent.state.store import StateStore

SKILLS_DIR = "src/guide_agent/skills"


@pytest.fixture
def state(tmp_path):
    return StateStore(tmp_path)


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    return AppConfig(llm=LLMConfig())


@pytest.fixture
def loader():
    return SkillLoader(SKILLS_DIR)


# ---------------------------------------------------------------------------
# build_search_query
# ---------------------------------------------------------------------------


def test_build_query_joins_with_pipe():
    q = build_search_query(["xss", "cross-site scripting", "dom xss"])
    assert q == "xss|cross-site scripting|dom xss"


def test_build_query_dedupes_case_insensitive():
    q = build_search_query(["xss", "XSS", "Xss", "cross-site"])
    assert q == "xss|cross-site"


def test_build_query_strips_whitespace():
    q = build_search_query(["  xss  ", "", "  ", "dom-xss"])
    assert q == "xss|dom-xss"


def test_build_query_handles_empty():
    assert build_search_query([]) == ""


# ---------------------------------------------------------------------------
# StateStore expansion cache
# ---------------------------------------------------------------------------


def test_get_expansion_returns_none_for_unknown(state):
    assert state.get_expansion("never-seen") is None


def test_set_and_get_expansion_roundtrip(state):
    state.set_expansion("xss", ["xss", "cross-site scripting", "dom xss"])
    cached = state.get_expansion("xss")
    assert cached is not None
    assert "xss" in cached
    assert "cross-site scripting" in cached


def test_set_expansion_normalizes_bug_class_case(state):
    state.set_expansion("PostMessage", ["postmessage", "window.postmessage"])
    # Stored under lowercase key
    assert state.get_expansion("postmessage") is not None
    assert state.get_expansion("PostMessage") is not None


def test_set_expansion_ensures_canonical_first(state):
    """The bug class itself must always be in the term list."""
    state.set_expansion("ssrf", ["server-side request forgery", "blind ssrf"])
    cached = state.get_expansion("ssrf")
    assert "ssrf" in cached


def test_set_expansion_deduplicates(state):
    state.set_expansion("xss", ["xss", "XSS", "xss", "dom xss"])
    cached = state.get_expansion("xss")
    # 'xss' (any case) + 'dom xss' = 2 unique
    assert len(cached) == 2


def test_delete_expansion(state):
    state.set_expansion("xss", ["xss", "dom xss"])
    state.delete_expansion("xss")
    assert state.get_expansion("xss") is None


# ---------------------------------------------------------------------------
# ExpansionBrain — LLM call mocked
# ---------------------------------------------------------------------------


def test_expansion_brain_parses_list_response(config, state, loader):
    brain = ExpansionBrain(config, state)
    stub = '["xss", "cross-site scripting", "dom xss"]'
    with patch.object(brain, "_single_turn", return_value=stub):
        terms = brain.expand("xss")
    assert terms == ["xss", "cross-site scripting", "dom xss"]


def test_expansion_brain_inserts_canonical_if_missing(config, state, loader):
    brain = ExpansionBrain(config, state)
    with patch.object(brain, "_single_turn", return_value='["cross-site scripting", "dom xss"]'):
        terms = brain.expand("xss")
    assert terms[0] == "xss"


def test_expansion_brain_lowercases_terms(config, state, loader):
    brain = ExpansionBrain(config, state)
    with patch.object(brain, "_single_turn", return_value='["XSS", "Cross-Site Scripting"]'):
        terms = brain.expand("xss")
    assert all(t == t.lower() for t in terms)


def test_expansion_brain_falls_back_to_canonical_on_non_list(config, state, loader):
    brain = ExpansionBrain(config, state)
    with patch.object(brain, "_single_turn", return_value='{"oops": "wrong shape"}'):
        terms = brain.expand("xss")
    assert terms == ["xss"]


def test_expansion_brain_dedupes_response(config, state, loader):
    brain = ExpansionBrain(config, state)
    with patch.object(brain, "_single_turn", return_value='["xss", "XSS", "xss", "dom xss"]'):
        terms = brain.expand("xss")
    assert terms.count("xss") == 1


def test_expansion_brain_handles_empty_bug_class(config, state, loader):
    brain = ExpansionBrain(config, state)
    terms = brain.expand("   ")
    assert terms == []


# ---------------------------------------------------------------------------
# ensure_expansion — cache wrap
# ---------------------------------------------------------------------------


def test_ensure_returns_cache_when_present(config, state, loader):
    state.set_expansion("xss", ["xss", "dom xss"])
    with patch("guide_agent.agent.expansion.ExpansionBrain") as mock_brain_cls:
        terms = ensure_expansion(config, state, loader, "xss")
    assert "xss" in terms
    mock_brain_cls.assert_not_called()  # No LLM call


def test_ensure_calls_brain_when_missing(config, state, loader):
    fake_brain = MagicMock()
    fake_brain.expand.return_value = ["xss", "cross-site scripting"]
    with patch(
        "guide_agent.agent.expansion.ExpansionBrain",
        return_value=fake_brain,
    ):
        terms = ensure_expansion(config, state, loader, "xss")
    assert "xss" in terms
    fake_brain.expand.assert_called_once_with("xss")
    # Cached for next time
    assert state.get_expansion("xss") is not None


def test_ensure_force_bypasses_cache(config, state, loader):
    state.set_expansion("xss", ["xss", "old-term"])
    fake_brain = MagicMock()
    fake_brain.expand.return_value = ["xss", "new-term"]
    with patch(
        "guide_agent.agent.expansion.ExpansionBrain",
        return_value=fake_brain,
    ):
        terms = ensure_expansion(config, state, loader, "xss", force=True)
    fake_brain.expand.assert_called_once()
    assert "new-term" in terms
    assert "old-term" not in terms


def test_ensure_falls_back_to_canonical_if_brain_empty(config, state, loader):
    fake_brain = MagicMock()
    fake_brain.expand.return_value = []
    with patch(
        "guide_agent.agent.expansion.ExpansionBrain",
        return_value=fake_brain,
    ):
        terms = ensure_expansion(config, state, loader, "xss")
    assert terms == ["xss"]


def test_ensure_handles_empty_bug_class(config, state, loader):
    assert ensure_expansion(config, state, loader, "   ") == []
