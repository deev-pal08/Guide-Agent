"""Tests for the conversation brain's confirmation parser.

We mock _single_turn so we don't actually call Claude. The shortcut paths
(digit replies, quit keywords) don't need the LLM at all.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from guide_agent.agent.conversation import (
    ConfirmationDecision,
    ConversationBrain,
    parse_confirmation,
)
from guide_agent.config import AppConfig, LLMConfig
from guide_agent.models import Phase, Proposal, ProposalOption
from guide_agent.skills.loader import SkillLoader
from guide_agent.state.store import StateStore

SKILLS_DIR = "src/guide_agent/skills"


@pytest.fixture
def brain(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    config = AppConfig(llm=LLMConfig())
    state = StateStore(tmp_path)
    loader = SkillLoader(SKILLS_DIR)
    return ConversationBrain(config, state, loader)


@pytest.fixture
def proposal():
    return Proposal(
        bug_class="postmessage",
        context_summary="test",
        options=[
            ProposalOption(
                label="Learn phase", phase=Phase.LEARN,
                description="x", rationale="y",
            ),
            ProposalOption(
                label="Practice phase", phase=Phase.PRACTICE,
                description="x", rationale="y",
            ),
            ProposalOption(
                label="Free choice", phase=None,
                description="x", rationale="y",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Shortcut paths — no LLM call needed
# ---------------------------------------------------------------------------


def test_quit_keyword_aborts(brain, proposal):
    decision = parse_confirmation(brain, proposal, "q")
    assert decision.action == "abort"


def test_quit_full_word_aborts(brain, proposal):
    for word in ("quit", "exit", "abort", "stop", "cancel"):
        decision = parse_confirmation(brain, proposal, word)
        assert decision.action == "abort", f"failed for {word!r}"


def test_digit_picks_phase_option(brain, proposal):
    decision = parse_confirmation(brain, proposal, "1")
    assert decision.action == "confirm"
    assert decision.phase == Phase.LEARN


def test_digit_picks_practice_phase(brain, proposal):
    decision = parse_confirmation(brain, proposal, "2")
    assert decision.action == "confirm"
    assert decision.phase == Phase.PRACTICE


def test_digit_picks_free_choice_routes_to_iterate(brain, proposal):
    decision = parse_confirmation(brain, proposal, "3")
    assert decision.action == "iterate"
    # The label of the free-choice option becomes the feedback
    assert "Free choice" in decision.iteration_feedback


def test_digit_out_of_range_falls_through_to_llm(brain, proposal):
    """Digit beyond options should NOT shortcut — it should call the LLM."""
    mock_response = '{"action": "iterate", "iteration_feedback": "99 is not an option"}'
    with patch.object(brain, "_single_turn", return_value=mock_response):
        decision = parse_confirmation(brain, proposal, "99")
    assert decision.action == "iterate"


# ---------------------------------------------------------------------------
# Free-text replies — LLM-backed
# ---------------------------------------------------------------------------


def test_free_text_confirm(brain, proposal):
    mock_response = (
        '{"action": "confirm", "phase": "learn", '
        '"research_mode": null, "target_hours": 4.0}'
    )
    with patch.object(brain, "_single_turn", return_value=mock_response):
        decision = parse_confirmation(brain, proposal, "yes give me 4h on learn")
    assert decision.action == "confirm"
    assert decision.phase == Phase.LEARN
    assert decision.target_hours == 4.0


def test_free_text_iterate(brain, proposal):
    mock_response = (
        '{"action": "iterate", "iteration_feedback": "harder reports needed"}'
    )
    with patch.object(brain, "_single_turn", return_value=mock_response):
        decision = parse_confirmation(brain, proposal, "harder reports needed")
    assert decision.action == "iterate"
    assert "harder" in decision.iteration_feedback


def test_free_text_research_with_mode(brain, proposal):
    mock_response = (
        '{"action": "confirm", "phase": "research", '
        '"research_mode": "gap_analysis", "target_hours": 5.0}'
    )
    with patch.object(brain, "_single_turn", return_value=mock_response):
        decision = parse_confirmation(brain, proposal, "research, gap analysis, 5h")
    assert decision.action == "confirm"
    assert decision.phase == Phase.RESEARCH
    assert decision.research_mode is not None
    assert decision.research_mode.value == "gap_analysis"


# ---------------------------------------------------------------------------
# ConfirmationDecision sanity
# ---------------------------------------------------------------------------


def test_confirmation_decision_defaults():
    d = ConfirmationDecision(action="confirm")
    assert d.phase is None
    assert d.research_mode is None
    assert d.target_hours == 3.0
    assert d.iteration_feedback == ""


# ---------------------------------------------------------------------------
# Initial proposal for a brand new bug class — no LLM call
# ---------------------------------------------------------------------------


def test_propose_new_class_returns_seed_options(brain):
    """Brand new bug class proposal is heuristic, no LLM."""
    proposal = brain._propose_new_class("brand-new-class")
    assert proposal.bug_class == "brand-new-class"
    assert len(proposal.options) >= 2
    # Should suggest learn phase as the entry point
    learn_option = next(o for o in proposal.options if o.phase == Phase.LEARN)
    assert "learn" in learn_option.label.lower()
